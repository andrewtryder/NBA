###
# Copyright (c) 2013-2014, spline
# All rights reserved.
#
#
###
# my libs
import json
import cPickle as pickle
from base64 import b64decode  # b64.
from calendar import timegm  # utc time.
import pytz  # utc time.
import datetime  # utc time.
# extra supybot libs.
import supybot.conf as conf
import supybot.ircmsgs as ircmsgs
import supybot.schedule as schedule
# supybot libs.
import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('NBA')
except:
    # Placeholder that allows to run the plugin on a bot
    # without the i18n module
    _ = lambda x:x

class NBA(callbacks.Plugin):
    """Add the help for "@plugin help NBA" here
    This should describe *how* to use this plugin."""
    threaded = True

    def __init__(self, irc):
        self.__parent = super(NBA, self)
        self.__parent.__init__(irc)
        # initial states for games.
        self.games = None
        self.nextcheck = None
        # now do our initial run.
        if not self.games:
            g = self._fetchgames()  # fetch our stuff.
            if g:  # if we get something back.
                self.games = g['games']
            # self.games = self._fetchgames()
        # now setup the empty channels dict.
        self.channels = {}
        self._loadpickle()  # load saved data into channels.
        # now setup the cron.
        def checknbacron():
            try:
                self.checknba(irc)
            except Exception, e:
                self.log.error("cron: ERROR: {0}".format(e))
                self.nextcheck = self._utcnow()+72000
        try:
            schedule.addPeriodicEvent(checknbacron, self.registryValue('checkInterval'), now=False, name='checknba')
        except AssertionError:
            try:
                schedule.removeEvent('checknba')
            except KeyError:
                pass
            schedule.addPeriodicEvent(checknbacron, self.registryValue('checkInterval'), now=False, name='checknba')

    def die(self):
        try:
            schedule.removeEvent('checknba')
        except KeyError:
            pass
        self.__parent.die()

    #####################
    # INTERNAL COMMANDS #
    #####################

    def _httpget(self, url):
        """General HTTP resource fetcher."""

        if self.registryValue('logURLs'):
            self.log.info(url)

        try:
            headers = {"User-Agent":"Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:17.0) Gecko/20100101 Firefox/17.0"}
            page = utils.web.getUrl(url, headers=headers)
            return page
        except Exception, e:
            self.log.error("ERROR opening {0} message: {1}".format(url, e))
            return None

    def _gctosec(self, s):
        """Convert seconds of statusclock into an integer of seconds remaining."""

        if ':' in s:
            l = s.split(':')
            return int(int(l[0]) * 60 + int(l[1]))
        else:
            try:
                return int(round(float(s)))
            except Exception, e:  # this seems to popup.
                self.log.info("_gctosec :: ERROR :: could not convert: {0} to float: {1}".format(s, e))
                return s

    ##########################
    # CHANNEL SAVE INTERNALS #
    ##########################

    def _loadpickle(self):
        """Load channel data from pickle."""

        try:
            datafile = open(conf.supybot.directories.data.dirize(self.name()+".pickle"), 'rb')
            try:
                dataset = pickle.load(datafile)
            finally:
                datafile.close()
        except IOError:
            return False
        # restore.
        self.channels = dataset["channels"]
        return True

    def _savepickle(self):
        """Save channel data to pickle."""

        data = {"channels": self.channels}
        try:
            datafile = open(conf.supybot.directories.data.dirize(self.name()+".pickle"), 'wb')
            try:
                pickle.dump(data, datafile)
            finally:
                datafile.close()
        except IOError:
            return False
        return True

    ############################
    # TIME AND TIME CONVERSION #
    ############################

    def _convertUTC(self, dtstring):
        """We convert our dtstrings in each game into UTC epoch seconds."""

        naive = datetime.datetime.strptime(str(dtstring), "%Y%m%d%H%M")
        local = pytz.timezone("US/Eastern")
        local_dt = local.localize(naive, is_dst=None)
        utc_dt = local_dt.astimezone(pytz.UTC) # convert from utc->local(tzstring).
        rtrstr = timegm(utc_dt.utctimetuple())  # return epoch seconds/
        return rtrstr

    def _utcnow(self):
        """Calculate Unix timestamp from GMT."""

        ttuple = datetime.datetime.utcnow().utctimetuple()
        return timegm(ttuple)

    ###################
    # GAMES INTERNALS #
    ###################

    def _fetchgames(self):
        """Returns a list of games."""

        url = b64decode('aHR0cDovL2RhdGEubmJhLmNvbS9kYXRhLzEwcy9qc29uL2Ntcy9ub3NlYXNvbi9zY29yZXMvZ2FtZXRyYWNrZXIuanNvbg==')
        html = self._httpget(url)
        if not html:
            self.log.error("ERROR: Could not _fetchgames.")
            return None
        # process json. throw this thing in a try/except block because I have no clue if it will break like nfl.com does.
        try:
            jsonf = json.loads(html.decode('utf-8'))
            # make sure we have games. this happens in the offseason.
            if 'game' not in jsonf['sports_content']:
                self.log.error("_fetchgames :: I did not even find games. Setting next check for one day.")
                self.nextcheck = self._utcnow() + 86400
                return None
            # also check for "games".
            games = jsonf['sports_content']['game']
            if len(games) == 0:
                self.log.error("_fetchgames :: I found no games in the json data.")
                return None
            # containers for output.
            gd = {}
            gd['games'] = {}
            # iterate over each game, extract out json, and throw into a dict.
            for game in games:
                dt = self._convertUTC(game['date']+game['time'])  # times in eastern.
                nbaid = game['id']  # unique ID. need it for finalgame.
                gamedate = game['date']  # need for finalgame.
                hometeam = game['home']['abbreviation']
                homescore = game['home']['score']
                awayteam = game['visitor']['abbreviation']
                awayscore = game['visitor']['score']
                status = int(game['period_time']['game_status'])  # numeric status.
                statustext = game['period_time']['period_status']  # text status like Halftime.
                statusclock = game['period_time']['game_clock']  # text clock.
                statusperiod = game['period_time']['period_value']  # quarter.
                gameid = gamedate+game['time']+awayteam+hometeam  # generate our own ids.
                # conditional here for playoffs.
                if 'playoffs' in game:  # found.
                    playoffs = game['playoffs']
                else:  # not found.
                    playoffs = None
                # add the dict.
                gd['games'][gameid] = {'dt':dt, 'hometeam':hometeam, 'homescore':homescore,
                              'awayteam':awayteam, 'awayscore':awayscore, 'status':status,
                              'statustext':statustext, 'statusclock':statusclock, 'statusperiod':statusperiod,
                              'nbaid':nbaid, 'gamedate':gamedate, 'playoffs':playoffs }
            # lets also grab sportsmeta.
            sc = jsonf['sports_content']['sports_meta']['season_meta']
            gd['meta'] = sc
            # now return games.
            return gd
        except Exception, e:
            self.log.info("_fetchgames: ERROR fetching games :: {0}".format(e))
            return None

    def _standings(self, optyear):
        """Fetches standings."""

        url = b64decode('aHR0cDovL2RhdGEubmJhLmNvbS9qc29uL2Ntcy8=') + optyear + '/standings/division.json'
        html = self._httpget(url)
        if not html:
            self.log.error("ERROR: Could not _finalgame.")
            return None
        # we should get back json. big try/except.
        try:
            tree = json.loads(html.decode('utf-8'))
            # container for output.
            ts = {}
            # lets now find/parse the json.
            confs = tree['sports_content']['standings']['conferences']
            for conf in confs:  # iterate over confs.
                divs = confs[conf]['divisions']
                for div in divs:  # iterate over divs.
                    teams =  confs[conf]['divisions'][div]['team']
                    for team in teams:  # iterate over teams and populate.
                        tm = team['abbreviation']
                        ts[tm] = team
            # now return the dict.
            return ts
        except Exception, e:  # something went wrong.
            self.log.error("_standings :: ERROR :: {0}".format(e))
            return None

    def _finalgame(self, gamedate, gameid):
        """Grabs the boxscore json and prints a final statline."""

        url = b64decode('aHR0cDovL2RhdGEubmJhLmNvbS9qc29uL2Ntcy9ub3NlYXNvbi9nYW1lLw==') + '%s/%s/boxscore.json' % (str(gamedate), str(gameid))
        html = self._httpget(url)
        if not html:
            self.log.error("ERROR: Could not _finalgame.")
            return None
        # process json. throw this thing in a try/except block.
        try:
            jsonf = json.loads(html.decode('utf-8'))
            game = jsonf['sports_content']['game']
            if len(game) == 0:
                self.log.error("_finalgame :: I found no games in the json data.")
                return None

            # output dict. we preset DD/TD for later.
            gamestats = {'Double-double':[], 'Triple-double':[]}
            # iterate over the home/visitor.
            for var in ['visitor', 'home']:
                team = game[var]['abbreviation']
                fgp = game[var]['stats']['field_goals_percentage']
                tpp = game[var]['stats']['three_pointers_percentage']
                ftp = game[var]['stats']['free_throws_percentage']
                to = game[var]['stats']['turnovers']
                rb = (int(game[var]['stats']['rebounds_offensive'])+int(game[var]['stats']['rebounds_defensive']))  # total rb.
                ptsl = sorted(game[var]['players']['player'], key=lambda t: int(t['points']), reverse=True)[0]  # sort by points
                astl = sorted(game[var]['players']['player'], key=lambda t: int(t['assists']), reverse=True)[0]  # sort by assists. below we sort by adding rebounds.
                rbll = sorted(game[var]['players']['player'], key=lambda x: (int(x['rebounds_offensive']) + int(x['rebounds_defensive'])), reverse=True)[0]
                # inject into our gamestats dict with the text.
                gamestats[team] = "{0}: {1} {2}: {3} {4}: {5} {6}: {7} {8}: {9}  {10} :: {11} {12} {13} {14} {15} {16} {17} {18} {19}".format(\
                      ircutils.bold("FG%"), fgp,
                      ircutils.bold("FT%"), ftp,
                      ircutils.bold("3PT%"), tpp,
                      ircutils.bold("TO"), to,
                      ircutils.bold("RB"), rb,
                      ircutils.bold(ircutils.underline("LEADERS")),
                      ircutils.bold("PTS"), ptsl['last_name'].encode('utf-8'), ptsl['points'],
                      ircutils.bold("AST"), astl['last_name'].encode('utf-8'), astl['assists'],
                      ircutils.bold("RB"), rbll['last_name'].encode('utf-8'), (int(rbll['rebounds_offensive'])+int(rbll['rebounds_defensive'])))
                # look for DD/TD
                for x in game[var]['players']['player']:  # iterate over.
                    tmp = {}  # we make a dict with the key as the stat for later.
                    tmp['rb'] = int(x['rebounds_offensive']) + int(x['rebounds_defensive'])
                    tmp['blocks'] = int(x['blocks'])
                    tmp['a'] = int(x['assists'])
                    tmp['p'] = int(x['points'])
                    tmp['s'] = int(x['steals'])
                    # we only inject into matching the category and stat if 10 or over.
                    matching = [str(z.upper()) + ": " + str(p) for (z, p) in tmp.items() if p >= 10]
                    if len(matching) == 2:  # dd. inject into gamestats in the right category.
                        gamestats['Double-double'].append("{0}({1}) :: {2}".format(x['last_name'].encode('utf-8'), team, " | ".join(matching)))
                    if len(matching) > 2:  # likewise with td.
                        gamestats['Triple-double'].append("{0}({1}) :: {2}".format(x['last_name'].encode('utf-8'), team, " | ".join(matching)))

            # return the dict.
            return gamestats
        except Exception, e:
            self.log.error("_finalgame: ERROR on {0} :: {1}".format(url, e))
            return None

    ###########################################
    # INTERNAL CHANNEL POSTING AND DELEGATION #
    ###########################################

    def _post(self, irc, message):
        """Posts message to a specific channel."""

        # first check if we have channels.
        if len(self.channels) == 0:  # bail if none.
            return
        # we do have channels. lets go and check where to put what.
        postchans = [k for (k, v) in self.channels.items() if v == 1]  # only channels with 1 = on.
        # iterate over each and post.
        for postchan in postchans:
            try:
                irc.queueMsg(ircmsgs.privmsg(postchan, message))
            except Exception as e:
                self.log.error("ERROR: Could not send {0} to {1}. {2}".format(message, postchan, e))

    ###########################
    # INTERNAL EVENT HANDLERS #
    ###########################

    def _boldleader(self, awayteam, awayscore, hometeam, homescore):
        """Conveinence function to bold the leader."""

        if (int(awayscore) > int(homescore)):  # visitor winning.
            return "{0} {1} {2} {3}".format(ircutils.bold(awayteam), ircutils.bold(awayscore), hometeam, homescore)
        elif (int(awayscore) < int(homescore)):  # home winning.
            return "{0} {1} {2} {3}".format(awayteam, awayscore, ircutils.bold(hometeam), ircutils.bold(homescore))
        else:  # tie.
            return "{0} {1} {2} {3}".format(awayteam, awayscore, hometeam, homescore)

    def _begingame(self, ev, m=None, p=None):
        """Handle start of game event. m = dict of team records for regular season. p = for playoffs"""

        if p:  # are we in playoffs mode?
            # EASTERN CONFERENCE 1ST ROUND - GAME 1 - SERIES TIED 0-0
            if p['round'] in ("1", "2", "3"):  # check round. 1, 2, 3 still conf. 4 = finals.
                r = p['conference'].upper() + "ERN CONFERENCE"  # EAST/WEST - ERN CONFERENCE.
            else:
                r = "NBA Finals"
            # next, the game.
            g = "GAME {0}".format(p['game_number'])
            # now the balance.
            s = "SERIES {0}-{1}".format(p['visitor_wins'], p['home_wins'])
            # now lets build the string.
            mstr = "({0}){1}@({2}){3} :: {4} :: {5} :: {6} :: {7}".format(p['visitor_seed'], ev['awayteam'], p['home_seed'], ev['hometeam'], r, g, s, ircutils.mircColor("TIPOFF", 'green'))
        elif m:  # we have metadata dict.
            # this is for season_stage 2 (regular)
            # NOP :: {u'name': u'New Orleans', u'abbreviation': u'NOP',
            # u'team_stats': {u'streak': u'W 4', u'rank': u'1', u'gb_conf': u'0.0', u'conf_win_loss': u'2-0',
            # u'clinched_division': u'0', u'wins': u'4', u'losses': u'0', u'l10': u'4-0', u'streak_num': u'4',
            # 'u'pct': u'1.000', u'div_rank': u'1', u'clinched_conference': u'0', u'gb_div': u'0.0',
            # u'home': u'1-0', u'div_win_loss': u'2-0', u'clinched_playoffs': u'0', u'road': u'3-0'},
            # u'team_key': u'New Orleans', u'nickname': u'Pelicans', u'id': u'1610612740'}
            # handle awayteam.
            if ev['awayteam'] in m:  # awayteam is found inside.
                at = "{0} ({1}-{2}, {3} away)".format(ev['awayteam'], m[ev['awayteam']]['team_stats']['wins'], m[ev['awayteam']]['team_stats']['losses'], m[ev['awayteam']]['team_stats']['road'])  # (3-7, 1-5 away)"
            else:  # awaytea mwas NOT found in dict.
                at = ev['awayteam']
            # handle hometeam.
            if ev['hometeam'] in m:  # awayteam is found inside.
                ht = "{0} ({1}-{2}, {3} home)".format(ev['hometeam'], m[ev['hometeam']]['team_stats']['wins'], m[ev['hometeam']]['team_stats']['losses'], m[ev['hometeam']]['team_stats']['home'])
            else:  # awaytea mwas NOT found in dict.
                ht = ev['hometeam']
            # now construct.
            mstr = "{0}@{1} :: {2}".format(at, ht, ircutils.mircColor("TIPOFF", 'green'))
        else:  # NO METADATA. JUST POST STARTGAME.
            mstr = "{0}@{1} :: {2}".format(ev['awayteam'], ev['hometeam'], ircutils.mircColor("TIPOFF", 'green'))
        # return.
        return mstr

    def _endgame(self, ev):
        """Handle end of game event."""

        gamestr = self._boldleader(ev['awayteam'], ev['awayscore'], ev['hometeam'], ev['homescore'])
        mstr = "{0} :: {1}".format(gamestr, ircutils.mircColor("FINAL", 'red'))
        return mstr

    def _halftime(self, ev):
        """Handle halftime event."""

        gamestr = self._boldleader(ev['awayteam'], ev['awayscore'], ev['hometeam'], ev['homescore'])
        mstr = "{0} :: {1}".format(gamestr, ircutils.mircColor("HALFTIME", 'yellow'))
        return mstr

    def _endhalftime(self, ev):
        """Handle end of game event."""

        gamestr = self._boldleader(ev['awayteam'], ev['awayscore'], ev['hometeam'], ev['homescore'])
        mstr = "{0} :: {1}".format(gamestr, ircutils.mircColor("Start 3rd Qtr", 'green'))
        return mstr

    def _endquarter(self, ev):
        """Handle end of quarter event."""

        ordinal = utils.str.ordinal(str(ev['statusperiod']))  # converts period into ordinal (1->1st, 2->2nd).
        gamestr = self._boldleader(ev['awayteam'], ev['awayscore'], ev['hometeam'], ev['homescore'])
        mstr = "{0} :: End of {1} Qtr.".format(gamestr, ordinal)
        return mstr

    def _closegame(self, ev):
        """Handle close game event."""

        gamestr = self._boldleader(ev['awayteam'], ev['awayscore'], ev['hometeam'], ev['homescore'])
        mstr = "{0} :: {1}".format(gamestr, ircutils.bold("Game is close in 4th quarter with under 1 minute remaining."))
        return mstr

    def _beginovertime(self, ev):
        """Handle start of overtime."""

        otper = "Start OT{0}".format(int(ev['statusperiod'])-4)  # should start with 5, which is OT1.
        gamestr = self._boldleader(ev['awayteam'], ev['awayscore'], ev['hometeam'], ev['homescore'])
        mstr = "{0} :: {1}".format(gamestr, ircutils.mircColor(otper, 'green'))
        return mstr

    def _endotquarter(self, ev):
        """Handle end of overtime quarter event."""

        statusperiod = int(ev['statusperiod'])-4
        ordinal = utils.str.ordinal(str(statusperiod))  # converts period into ordinal (1->1st, 2->2nd).
        gamestr = self._boldleader(ev['awayteam'], ev['awayscore'], ev['hometeam'], ev['homescore'])
        mstr = "{0} :: End of {1} OT.".format(gamestr, ordinal)
        return mstr

    ##################
    # DEBUG COMMANDS #
    ##################
    
    def nbadebug(self, irc, msg, args):
        """
        DEBUG COMMAND
        """
    
        for (i, g) in self.games.items():
            irc.reply("{0} :: {1}".format(i, g))
    
    nbadebug = wrap(nbadebug)

    ###################
    # PUBLIC COMMANDS #
    ###################

    def nbachannel(self, irc, msg, args, op, optchannel):
        """<add #channel|del #channel|list>

        Add or delete a channel from NBA output.
        Use list to list channels we output to.
        Ex: add #channel OR del #channel OR list
        """

        # first, lower operation.
        op = op.lower()
        # next, make sure op is valid.
        validop = ['add', 'list', 'del']
        if op not in validop:  # test for a valid operation.
            irc.reply("ERROR: '{0}' is an invalid operation. It must be be one of: {1}".format(op, " | ".join([i for i in validop])))
            return
        # if we're not doing list (add or del) make sure we have the arguments.
        if (op != 'list'):
            if not optchannel:
                irc.reply("ERROR: add and del operations require a channel and team. Ex: add #channel or del #channel")
                return
            # we are doing an add/del op.
            optchannel = optchannel.lower()
            # make sure channel is something we're in
            if optchannel not in irc.state.channels:
                irc.reply("ERROR: '{0}' is not a valid channel. You must add a channel that we are in.".format(optchannel))
                return
        # main meat part.
        # now we handle each op individually.
        if op == 'add':  # add output to channel.
            self.channels[optchannel] = 1  # add it and on.
            self._savepickle()  # save.
            irc.reply("I have enabled NBA status updates on {0}".format(optchannel))
        elif op == 'list':  # list channels
            if len(self.channels) == 0:  # no channels.
                irc.reply("ERROR: I have no active channels defined. Please use the nbachannel add operation to add a channel.")
            else:   # we do have channels.
                for (k, v) in self.channels.items():  # iterate through and output translated keys.
                    if v == 0:  # swap 0/1 into OFF/ON.
                        irc.reply("{0} :: OFF".format(k))
                    elif v == 1:
                        irc.reply("{0} :: ON".format(k))
        elif op == 'del':  # delete an item from channels.
            if optchannel in self.channels:  # id is already in.
                del self.channels[optchannel]  # remove it.
                self._savepickle()  # save.
                irc.reply("I have successfully removed {0}".format(optchannel))
            else:  # id was NOT in there.
                irc.reply("ERROR: I do not have {0} in {1}".format(optarg, optchannel))

    nbachannel = wrap(nbachannel, [('checkCapability', 'admin'), ('somethingWithoutSpaces'), optional('channel')])

    def nbaon(self, irc, msg, args, channel):
        """
        Enable NBA scoring in channel.
        """

        # channel
        channel = channel.lower()
        # check if op.
        if not irc.state.channels[channel].isOp(msg.nick):
            irc.reply("ERROR: You must be an op in this channel for this command to work.")
            return
        # check now.
        if channel in self.channels:
            self.channels[channel] = 1
            irc.reply("I have turned on NBA livescoring for {0}".format(channel))
        else:
            irc.reply("ERROR: {0} is not in any known channels.".format(channel))

    nbaon = wrap(nbaon, [('channel')])

    def nbaoff(self, irc, msg, args, channel):
        """
        Disable NBA scoring in channel.
        """

        # channel
        channel = channel.lower()
        # check if op.
        if not irc.state.channels[channel].isOp(msg.nick):
            irc.reply("ERROR: You must be an op in this channel for this command to work.")
            return
        # check now.
        if channel in self.channels:
            self.channels[channel] = 0
            irc.reply("I have turned off NBA livescoring for {0}".format(channel))
        else:
            irc.reply("ERROR: {0} is not in any known channels.".format(channel))

    nbaoff = wrap(nbaoff, [('channel')])

    #############
    # MAIN LOOP #
    #############

    def checknba(self, irc):
    #def checknba(self, irc, msg, args):
        """
        Main loop.
        """

        # before anything, check if nextcheck is set and is in the future.
        if self.nextcheck:  # set
            utcnow = self._utcnow()
            if self.nextcheck > utcnow:  # in the future so we backoff.
                self.log.info("checknba: nextcheck is {0}s in the future.".format(self.nextcheck-utcnow))
                return
            else:  # in the past so lets reset it. this means that we've reached the time where firstgametime should begin.
                self.log.info("checknba: nextcheck has passed. we are resetting and continuing normal operations.")
                self.nextcheck = None
        # we must have initial games. bail if not.
        # games + meta.
        if not self.games:
            g = self._fetchgames()  # fetch our stuff.
            if (g and 'games' in g):  # if we get something back.
                self.games = g['games']  # games1
        # check and see if we have initial games, again, but bail if not.
        if not self.games:
            self.log.error("checknba: ERROR: I did not have any games in self.games")
            return
        else:  # setup the initial games.
            games1 = self.games
        # now we must grab the new status to compare with.
        g = self._fetchgames()  # fetch our stuff.
        # make sure we get something back.
        if ((g) and ('games' in g) and ('meta' in g)):
            games2 = g['games']  # games
            meta = g['meta']  # metadata.
            self.log.info("META: {0}".format(meta))
        else:  # something went wrong so we bail.
            self.log.error("checknba: ERROR: fetching games2 failed.")
            return

        # main handler for event changes.
        # we go through and have to match specific conditions based on json changes.
        for (k, v) in games1.items():  # iterate over games.
            if k in games2:  # must mate keys between games1 and games2.
                # GAME STATUS CHANGES: IE: START OR FINISH.
                if (v['status'] != games2[k]['status']):
                    if ((v['status'] == 1) and (games2[k]['status'] == 2)):  # 1-> 2 means the game started.
                        self.log.info("checknba: begin tracking {0}".format(k))
                        # now, we use the metadata above and check if stage is in "2" (regular season).
                        # no checks for meta because if meta does not exist, it will fail above.
                        if meta['season_stage'] == "2":  # we're in regular season.
                            # fetch the dict of regular season standings.
                            optyear = meta['standings_season_year']  # fetch the year.
                            standings = self._standings(optyear)  # http call to the standings.
                            if standings:   # if we get something back, feed meta into begingame.
                                mstr = self._begingame(games2[k], m=standings, p=None)
                            else:  # something broke fetching standings.
                                mstr = self._begingame(games2[k], m=None, p=None)
                        elif meta['season_stage'] == "4":  # postseason.
                            if 'playoffs' in games2[k]:  # if we find the data, send it in.
                                mstr = self._begingame(games2[k], m=None, p=games2[k]['playoffs'])
                            else:  # something went wrong.
                                mstr = self._begingame(games2[k], m=None, p=None)
                        else:  # other point in the year.
                            mstr = self._begingame(games2[k], m=None, p=None)
                        # we're done. post the begin game.
                        self._post(irc, mstr)
                    elif ((v['status'] == 2) and (games2[k]['status'] == 3)):  # 2-> 3 means the game ended.
                        self.log.info("checknba: endgame tracking {0}".format(k))
                        mstr = self._endgame(games2[k])
                        self._post(irc, mstr)
                        # final game stats and info. should we print it in this channel?
                        #if self.registryValue('displayGameStats', msg[0]):
                        # try and get finalgame info. print if we do.
                        finalgame = self._finalgame(v['gamedate'], v['nbaid'])
                        if finalgame:  # we got it. iterate over the keys (teams) and expand values (statlines) for irc.
                            for (fgk, fgv) in finalgame.items():
                                if len(fgv) != 0:  # if items in the dict.
                                    if isinstance(fgv, list):  # special instance case for DD/TD.
                                        fgv = " || ".join(fgv)  # join into a string.
                                    # format the text/string for output.
                                    fgtxt = "{0} :: {1}".format(ircutils.bold(fgk), fgv)
                                    self._post(irc, fgtxt)
                # BELOW ARE EVENTS THAT CAN ONLY HAPPEN WHEN A GAME IS ACTIVE.
                elif ((v['status'] == 2) and (games2[k]['status'] == 2)):
                    # START OF OVERTIME QUARTER.
                    if ((v['statusperiod'] != games2[k]['statusperiod']) and (int(games2[k]['statusperiod']) > 4)):
                        mstr = self._beginovertime(games2[k])
                        self._post(irc, mstr)
                    # END OF QUARTER. (statusclock changed and the new is 0.0 (ie: 4.0->0.0)) but not for halftime.
                    if ((v['statusclock'] != games2[k]['statusclock']) and (games2[k]['statusclock'] == "0.0")):
                        if ((v['statusperiod'] != "2") and (games2[k]['statusperiod'] != "2") and (int(games2[k]['statusperiod']) < 4)): # 1, 3rd.
                            mstr = self._endquarter(games2[k])
                            self._post(irc, mstr)
                        if (int(games2[k]['statusperiod']) > 4):  # this will only fire when a quarter ends but not end of game.
                            if (games2[k]['awayscore'] == games2[k]['homescore']):  # only fire this if OT ends in a tie. 
                                mstr = self._endotquarter(games2[k])
                                self._post(irc, mstr)
                    # HANDLE GOING IN AND OUT OF HALFTIME.
                    if (v['statustext'] != games2[k]['statustext']):
                        # GAME GOES TO HALFTIME.
                        if (games2[k]['statustext'] == "Halftime"):
                            mstr = self._halftime(games2[k])
                            self._post(irc, mstr)
                        # GAME STARTS BACK FROM HALFTIME.
                        if (games2[k]['statustext'] == "3rd Qtr"):
                            mstr = self._endhalftime(v)
                            self._post(irc, mstr)
                    # HANDLE NOTIFICATION IF THERE IS A CLOSE GAME. ONLY FIRES AT UNDER 60S LEFT in 4TH QUARTER OR GREATER.
                    if ((int(games2[k]['statusperiod']) > 3) and (self._gctosec(v['statusclock']) >= 60) and (self._gctosec(games2[k]['statusclock']) < 60) and (abs(int(games2[k]['awayscore'])-int(games2[k]['homescore'])) < 8)):
                        mstr = self._closegame(games2[k])
                        self._post(irc, mstr)

        # now that we're done. swap games2 into self.games so things reset.
        self.games = games2
        self.log.info("finished checking.")
        # we're now all done processing the games and resetting. next, we must determine when
        # the nextcheck will be. this is completely dependent on the games and their statuses.
        # there are three conditions that have to be checked and acted on accordingly.
        gamestatuses = set([v['status'] for (k, v) in games2.items()])  # grab statuses from games and unique.
        # main loop.
        if (2 in gamestatuses):  # active games.
            self.nextcheck = None  # basically just reset nextcheck and continue.
        else:  # no active games. games are only in the future or completed.  we must determine what our nextcheck should be.
            utcnow = self._utcnow()  # grab UTC now.
            if (1 not in gamestatuses):  # this should mean all are done but no future games yet. ie only 3 in gamestatuses.
                # we need to check here if 3 is the only thing in the subset.
                self.log.info("checknba: all games are final but I don't have future games. nextcheck in 10 minutes.")
                self.nextcheck = utcnow+600  # back off for 10minutes.
            else:  # no active games but ones in the future. ie: 3 and 1 but not 2.
                self.log.info("checknba: no active games right now. we will set nextcheck in the future.")
                firstgametime = sorted([v['dt'] for (k, v) in games2.items() if v['status'] == 1])[0]  # sort future games, return the earliest.
                if utcnow > firstgametime:  # if we have passed the first game time (8:01 and start is 8:00)
                    fgtdiff = abs(firstgametime-utcnow)  # get how long ago the first game should have been.
                    if fgtdiff < 3601:  # if less than an hour ago, just basically pass.
                        self.log.info("checknba: firstgametime has passed ({0}s ago) but is under an hour so we're passing.".format(fgtdiff))
                        self.nextcheck = None
                    else:  # over an hour. consider stale.
                        self.log.info("checknba: firstgametime is over an hour late ({0}s) so we're going to backoff for 10 minutes.".format(fgtdiff))
                        self.nextcheck = utcnow+600
                else:  # firstgametime is in the future. we set based on this time.
                    self.log.info("checknba: firstgametime is in the future. we're setting it {0} seconds from now.".format(firstgametime-utcnow))
                    self.nextcheck = firstgametime

    #checknba = wrap(checknba)

Class = NBA

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:

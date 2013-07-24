###
# Copyright (c) 2013, spline
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
            self.games = self._fetchgames()
        # now setup the empty channels dict.
        self.close60 = {}
        self.channels = {}
        self._loadpickle()  # load saved data into channels.
        # now setup the cron.
        def checknbacron():
            self.checknba(irc)
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

    def _httpget(self, url, h=None, d=None, l=True):
        """General HTTP resource fetcher. Pass headers via h, data via d, and to log via l."""

        if self.registryValue('logURLs') and l:
            self.log.info(url)

        try:
            if h and d:
                page = utils.web.getUrl(url, headers=h, data=d)
            else:
                page = utils.web.getUrl(url)
            return page
        except utils.web.Error as e:
            self.log.error("ERROR opening {0} message: {1}".format(url, e))
            return None

    def _gctosec(self, s):
        """Convert seconds of statusclock into an integer of seconds remaining."""

        if ':' in s:
            l = s.split(':')
            return int(int(l[0]) * 60 + int(l[1]))
        else:
            return int(round(float(s)))

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
        headers = {"User-Agent":"Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:17.0) Gecko/20100101 Firefox/17.0"}
        html = self._httpget(url, h=headers)
        if not html:
            self.log.error("ERROR: Could not _fetchgames.")
            return None
        # process json.
        jsonf = json.loads(html.decode('utf-8'))
        games = jsonf['sports_content']['game']
        if len(games) == 0:
            self.log.error("_fetchgames :: I found no games in the json data.")
            return None
        # dict for output.
        gd = {}
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
            # add the dict.
            gd[gameid] = {'dt':dt, 'hometeam':hometeam, 'homescore':homescore,
                          'awayteam':awayteam, 'awayscore':awayscore, 'status':status,
                          'statustext':statustext, 'statusclock':statusclock,
                          'statusperiod':statusperiod, 'nbaid':nbaid, 'gamedate':gamedate }
        # now return games.
        return gd

    def _finalgame(self, gamedate, gameid):
        """Grabs the boxscore json and prints a final statline."""

        url = b64decode('aHR0cDovL2RhdGEubmJhLmNvbS9qc29uL2Ntcy9ub3NlYXNvbi9nYW1lLw==') + '%s/%s/boxscore.json' % (str(gamedate), str(gameid))
        headers = {"User-Agent":"Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:17.0) Gecko/20100101 Firefox/17.0"}
        html = self._httpget(url, h=headers)
        if not html:
            self.log.error("ERROR: Could not _finalgame.")
            return None
        # process json.
        jsonf = json.loads(html.decode('utf-8'))
        game = jsonf['sports_content']['game']
        if len(game) == 0:
            self.log.error("_finalgame :: I found no games in the json data.")
            return None
        # throw this thing in a try/except block.
        try:
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

    def _begingame(self, ev):
        """Handle start of game event."""

        mstr = "{0}@{1} :: {2}".format(ev['awayteam'], ev['hometeam'], ircutils.mircColor("TIPOFF", 'green'))
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

    ###################
    # PUBLIC COMMANDS #
    ###################

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

    def nbascores(self, irc, msg, args):
        """
        NBA Scores.
        """

        if self.nextcheck:
            irc.reply("NEXTCHECK: {0}".format(self.nextcheck))

        ###
        irc.reply("games: {0}".format(self.games))

        url = b64decode('aHR0cDovL2RhdGEubmJhLmNvbS9kYXRhLzEwcy9qc29uL2Ntcy9ub3NlYXNvbi9zY29yZXMvZ2FtZXRyYWNrZXIuanNvbg==')
        html = self._httpget(url)
        if not html:
            irc.reply("Error fetching: {0}".format(url))
            return
        jsonf = json.loads(html.decode('utf-8'))
        games = jsonf['sports_content']['game']
        scores = []
        for game in games:
            gamestatus = int(game['period_time']['game_status'])
            awayteam = game['visitor']['abbreviation']
            awayscore = game['visitor']['score']
            hometeam = game['home']['abbreviation']
            homescore = game['home']['score']
            pstatus = game['period_time']['period_status']
            ptime = game['period_time']['game_clock']
            if gamestatus in (1, 2):
                scores.append("{0} {1} - {2} {3} :: {4} {5}".format(awayteam, awayscore, hometeam, homescore, pstatus, ptime))

        if len(games) != 0:
            irc.reply(" | ".join([i for i in scores]))
        else:
            irc.reply("No NBA games.")

    nbascores = wrap(nbascores)

    #############
    # MAIN LOOP #
    #############

    def checknba(self, irc):
        """
        Main loop.
        """

        # before anything, check if nextcheck is set and is in the future.
        if self.nextcheck:  # set
            utcnow = self._utcnow()
            if self.nextcheck > utcnow:  # in the future so we backoff.
                return
            else:  # in the past so lets reset it. this means that we've reached the time where firstgametime should begin.
                self.log.info("checknba: nextcheck has passed. we are resetting and continuing normal operations.")
                self.nextcheck = None
        # we must have initial games. bail if not.
        if not self.games:
            self.games = self._fetchgames()
            return
        # check and see if we have initial games, again, but bail if no.
        if not self.games:
            self.log.error("checknba: I did not have any games in self.games")
            return
        else:  # setup the initial games.
            games1 = self.games
        # now we must grab the new status.
        games2 = self._fetchgames()
        if not games2:  # something went wrong so we bail.
            self.log.error("checknba: fetching games2 failed.")
            return

        # main handler for event changes.
        # we go through and have to match specific conditions based on json changes.
        for (k, v) in games1.items():  # iterate over games.
            if k in games2:  # must mate keys between games1 and games2.
                # first, check for status changes.
                if (v['status'] != games2[k]['status']):
                    if ((v['status'] == 1) and (games2[k]['status'] == 2)):  # 1-> 2 means the game started.
                        self.log.info("checknba: begin tracking {0}".format(k))
                        mstr = self._begingame(games2[k])
                        self._post(irc, mstr)
                    elif ((v['status'] == 2) and (games2[k]['status'] == 3)):  # 2-> 3 means the game ended.
                        self.log.info("checknba: endgame tracking {0}".format(k))
                        mstr = self._endgame(games2[k])
                        self._post(irc, mstr)
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
                        # delete any close60 key if present since the game is over.
                        if k in self.close60:
                            del self.close60[k]
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
                    # HANDLE NOTIFICATION IF THERE IS A CLOSE GAME.
                    if ((int(games2[k]['statusperiod']) > 3) and (self._gctosec(games2[k]['statusclock']) < 60) and (abs(int(games2[k]['awayscore'])-int(games2[k]['homescore'])) < 8)):
                        if k not in self.close60:  # make sure we're not repeating.
                            self.close60[k] = True  # set key so we do not repeat.
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
        else:  # no active games. we must determine what our nextcheck should be.
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
                        self.log.info("checknba: firstgametime has passed but is under an hour so we're passing.")
                        self.nextcheck = None
                    else:  # over an hour. consider stale.
                        self.log.info("checknba: firstgametime is over an hour from now so we're going to backoff for 10 minutes.")
                        self.nextcheck = utcnow+600
                else:  # firstgametime is in the future. we set based on this time.
                    self.log.info("checknba: firstgametime is in the future. we're setting it {0} seconds from now.".format(firstgametime-utcnow))
                    self.nextcheck = firstgametime


Class = NBA

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:

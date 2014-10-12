###
# Copyright (c) 2013-2014, spline
# All rights reserved.
#
#
###

from supybot.test import *

class NBATestCase(ChannelPluginTestCase):
    plugins = ('NBA',)
    
    def testNBA(self):
        self.assertResponse('nbachannel add #test', "I have enabled NBA status updates on #test")
        self.assertResponse('nbachannel del #test', "I have successfully removed #test")
    


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:

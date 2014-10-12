###
# Copyright (c) 2013-2014, spline
# All rights reserved.
#
#
###

from supybot.test import *

class NBATestCase(PluginTestCase):
    plugins = ('NBA',)
    
    def testNBA(self):
        self.assertNotError('nbachannel add #test')
        self.assertNotError('nbachannel del #test')
        self.assertError('nbaon')
        self.assertError('nbaoff')
    


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:

import time
import socket

import pulsar
from pulsar.utils.test import test

# you need to pass functions, you cannot pass lambdas
def testrun(actor):
    return actor.aid


class TestPulsarClient(test.TestCase):
    
    def client(self):
        actor = pulsar.get_actor()
        arbiter = actor.arbiter
        c = pulsar.PulsarClient.connect(arbiter.address)
        self.assertFalse(c.async)
        return c
        
    def testPing(self):
        c = self.client()
        self.assertEqual(c.ping(), 'pong')
        self.assertEqual(c.received, 1)
        self.assertEqual(c.ping(), 'pong')
        self.assertEqual(c.received, 2)
        
    def testEcho(self):
        c = self.client()
        self.assertEqual(c.echo('Hello!'), 'Hello!')
        self.assertEqual(c.echo('Ciao!'), 'Ciao!')
        self.assertEqual(c.received, 2)
        
    def testQuit(self):
        c = self.client()
        self.assertEqual(c.ping(), 'pong')
        self.assertEqual(c.quit(), True)
        self.assertRaises(socket.error, c.ping)
        
    #def testRun(self):
    #    c = self.client()
    #    result = c.run(testrun)
    #    self.assertEqual(result, 'arbiter')
        
    def testInfo(self):
        c = self.client()
        info = c.info()
        self.assertTrue(info)
        self.assertEqual(len(info['monitors']), 1)
        self.assertEqual(info['monitors'][0]['name'], 'test')
        
    def testClose(self):
        c = self.client()
        info = c.info()
        connections1 = info['server']['active_connections']
        c2 = self.client()
        info = c2.info()
        connections2 = info['server']['active_connections']
        self.assertEqual(connections1+1, connections2)
        # lets drop one
        c.close()
        # give it some time
        time.sleep(0.2)
        info = c2.info()
        connections3 = info['server']['active_connections']
        self.assertEqual(connections1, connections3)
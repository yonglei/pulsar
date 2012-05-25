import os
import sys
import time

import pulsar

from .actor import Actor
from .defer import async, iteritems, itervalues, range, NOT_DONE
from .proxy import ActorCallBacks
from .mailbox import Queue


__all__ = ['Monitor', 'PoolMixin']


class PoolMixin(object):
    '''Not an actor per se, this is a mixin for :class:`Actor`
which manages a pool (group) of actors. Given an :attr:`actor_class`
it makes sure there are always :attr:`num_actors` alive.
It is used by both the :class:`Arbiter` and the :class:`Monitor` classes.

.. attribute:: MANAGED_ACTORS

    dictionary with keys given by actor's ids and values by
    :class:`ActorProxyMonitor` instances. These are the actors managed by the
    pool.
    
.. attribute:: num_actors

    Number of actors to manage.
    
    Default ``0`` any number of actors.
'''
    CLOSE_TIMEOUT = 3
    JOIN_TIMEOUT = 1.0
    actor_class = Actor
    '''The class derived form :class:`Actor` which the monitor manages
during its life time.

    Default: :class:`Actor`'''
    
    def on_init(self, actor_class=None, num_actors=0, **kwargs):
        self._spawing = 0
        self._managed_actors = {}
        self.num_actors = num_actors or 0
        self.actor_class = actor_class or self.actor_class
    
    def __call__(self):
        if self.running():
            return self.on_task()
            
    def ready(self):
        return True
        
    def actorparams(self):
        '''Return a dictionary of parameters to be passed to the
spawn method when creating new actors.'''
        return {}
        
    def get_actor(self, aid):
        a = Actor.get_actor(self, aid)
        if not a and aid in self.MANAGED_ACTORS:
            a = self.MANAGED_ACTORS[aid]
        return a
               
    @property
    def MANAGED_ACTORS(self):
        return self._managed_actors
    
    def manage_actors(self, terminate=False, stop=False, manage=True):
        '''Remove :class:`Actor` which are not alive from the
:class:`PoolMixin.MANAGED_ACTORS` and return the number of actors still alive.

:parameter terminate: if ``True`` force termination of alive actors.
:parameter stop: if ``True`` stops all alive actor.
:parameter manage: if ``True`` it checks if alive actors are still responsive.
'''
        ACTORS = self.MANAGED_ACTORS
        linked = self._linked_actors
        alive = 0
        for aid, actor in list(iteritems(ACTORS)):
            if not actor.is_alive():
                actor.join(self.JOIN_TIMEOUT)
                ACTORS.pop(aid)
                linked.pop(aid,None)
            else:
                alive += 1
                if terminate:
                    actor.terminate()
                    actor.join(self.JOIN_TIMEOUT)
                elif stop:
                    actor.stop(self)
                elif manage:
                    self.manage_actor(actor)
        return alive
    
    def manage_actor(self, actor):
        '''This function is overritten by the arbiter'''
        pass
    
    def spawn_actors(self):
        '''Spawn new actors if needed.'''
        to_spawn = self.num_actors - len(self.MANAGED_ACTORS)
        if self.num_actors and to_spawn > 0 and not self._spawing:
            for _ in range(to_spawn):
                self.spawn_actor()
    
    def stop_actors(self):
        """Maintain the number of workers by spawning or killing
as required."""
        if self.num_actors:
            num_to_kill = len(self.MANAGED_ACTORS) - self.num_actors
            for i in range(num_to_kill, 0, -1):
                w, kage = 0, sys.maxsize
                for worker in itervalues(self.MANAGED_ACTORS):
                    age = worker.age
                    if age < kage:
                        w, kage = w, age
                self.stop_actor(w)
                
    def stop_actor(self, actor):
        raise NotImplementedError()
    
    @async
    def close_actors(self):
        '''Close all managed :class:`Actor`.'''
        start = time.time()
        # Stop all of them
        to_stop = self.manage_actors(stop=True)
        while to_stop:
            yield NOT_DONE
            to_stop = self.manage_actors(manage=False)
            dt = time.time() - start
            if dt > self.CLOSE_TIMEOUT:
                self.log.warn('Cannot stop %s actors.' % to_stop)
                to_stop = self.manage_actors(terminate=True)
                self.log.warn('terminated %s actors.' % to_stop)
                to_stop = 0
        

class Monitor(PoolMixin, Actor):
    '''A monitor is a special :class:`Actor` which shares
the same :class:`IOLoop` with the :class:`Arbiter` and therefore lives in
the main process domain.
The Arbiter manages monitors which in turn manage a set of :class:`Actor`
performing similar tasks.

In other words, you may have a monitor managing actors for serving HTTP
requests on a given port, another monitor managing actors consuming tasks
from a task queue and so forth. You can think of :class:`Monitor` as
managers of pools of :class:`Actor`.

Monitors are created by invoking the :meth:`Arbiter.add_monitor`
functions and not by directly invoking the constructor. Therefore
adding a new monitor to the arbiter follows the pattern::

    import pulsar
    
    m = pulsar.arbiter().add_monitor(pulsar.Monitor,'mymonitor')
    
You can also create a monitor with a distributed queue as IO mechanism::

    from multiprocessing import Queue
    import pulsar
    
    m = pulsar.arbiter().add_monitor(pulsar.Monitor,
                                     'mymonitor',
                                     ioqueue = Queue())

Monitors with distributed queues manage CPU-bound :class:`Actors`.
'''
    socket = None
    
    @property
    def cpubound(self):
        return False
    
    def isprocess(self):
        return False
    
    def is_monitor(self):
        return True
    
    def monitor_task(self):
        '''Monitor specific task called by the :meth:`Monitor.on_task`
:ref:`actor callback <actor-callbacks>` at each iteration in the event loop.
By default it does nothing.'''
        pass
    
    # HOOKS        
    def on_task(self):
        '''Overrides the :meth:`Actor.on_task`
:ref:`actor callback <actor-callbacks>` to perform
the monitor :class:`IOLoop` tasks, which are:

* To maintain a responsive set of actors ready to perform their duty.
* To perform its own tasks.

The implementation goes as following:

* It calls :meth:`PoolMixin.manage_actors` which removes from the live
  actors dictionary all actors which are not alive.
* Spawn new actors if required by calling :meth:`PoolMixin.spawn_actors`
  and :meth:`PoolMixin.stop_actors`.
* Call :meth:`Monitor.monitor_task` which performs the monitor specific
  task.
  
Users shouldn't need to override this method, but use
:meth:`Monitor.monitor_task` instead.'''
        self.manage_actors()
        self.spawn_actors()
        self.stop_actors()
        return self.monitor_task()
            
    def on_stop(self):
        '''Overrides the :meth:`Actor.on_stop`
:ref:`actor callback <actor-callbacks>` to stop managed actors.'''
        return self.close_actors()
        
    # OVERRIDES INTERNALS
    
    def _make_name(self):
        return 'Monitor-{0}({1})'.format(self.actor_class.code(),self.aid)
    
    def _get_requestloop(self):
        '''Return the arbiter request loop.'''
        return self.arbiter.requestloop
    
    def _run(self):
        pass
    
    @property
    def multithread(self):
        return self.cfg.concurrency == 'thread'
    
    @property
    def multiprocess(self):
        return self.cfg.concurrency == 'process'
    
    def spawn_actor(self):
        '''Spawn a new actor and add its :class:`ActorProxyMonitor`
 to the :attr:`PoolMixin.MANAGED_ACTORS` dictionary.'''
        ad =  self.arbiter.spawn(self.actor_class,
                                 monitor=self,
                                 ioqueue=self.ioqueue,
                                 monitors=self.arbiter.get_all_monitors(),
                                 commands_set=self.commands_set,
                                 params=self._params,
                                 **self.actorparams())
        self._spawing += 1
        return ad.add_callback(self._spawn_actor)
    
    def _spawn_actor(self, proxy):
        self._spawing -= 1
        monitor = self.arbiter.MANAGED_ACTORS[proxy.aid]
        self.MANAGED_ACTORS[proxy.aid] = monitor
        return proxy
    
    def stop_actor(self, actor):
        if not actor.is_alive():
            self.MANAGED_ACTORS.pop(actor.aid)
        else:
            return actor.proxy.stop()
        
    def info(self, full = False):
        if full:
            requests = []
            proxy = self.proxy
            for w in itervalues(self.MANAGED_ACTORS):
                requests.append(proxy.info(w))
            return ActorCallBacks(self,requests).add_callback(self._info)
        else:
            return self._info()
        
    def _info(self, result = None):
        if not result:
            result = [a.local_info() for a in self.MANAGED_ACTORS.values()] 
        tq = self.ioqueue
        data = {'actor_class':self.actor_class.code(),
                'workers': result,
                'num_actors':len(self.MANAGED_ACTORS),
                'concurrency':self.cfg.concurrency,
                'listen':str(self.socket),
                'name':self.name,
                'age':self.age}
        if tq is not None:
            if isinstance(tq,Queue):
                tqs = 'multiprocessing.Queue'
            else:
                tqs = str(tq)
            data.update({'ioqueue': tqs,
                         'ioqueue_size': tq.qsize()})
        return self.on_info(data)
        
    def get_actor(self, aid):
        '''Delegate get_actor to the arbiter'''
        return self.arbiter.get_actor(aid)
        
    
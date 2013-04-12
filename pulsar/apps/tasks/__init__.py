'''\
Pulsar ships with an asynchronous :class:`TaskQueue` built on top
:ref:`pulsar application framework <apps-framework>`. Task queues are used
as a mechanism to distribute work across threads/processes or machines.
Pulsar :class:`TaskQueue` is highly customizable, it can run in multi-threading
or multiprocessing (default) mode and can share :class:`task.Task` across
several machines.
By creating :class:`models.Job` classes in a similar way you do for celery_,
this application gives you all you need for running them with very
little setup effort::

    from pulsar.apps import tasks

    tq = tasks.TaskQueue(tasks_path=['path.to.tasks.*'])
    tq.start()
    
To get started, follow the these points:

* Create the script which runs your application, in the
  :ref:`taskqueue tutorial <tutorials-taskqueue>` the script is called
  ``manage.py``.
* Create the modules where :ref:`jobs <app-taskqueue-job>` are implemented. It
  can be a directory containing several submodules as explained in the
  :ref:`task paths parameter <app-tasks_path>`.
  

.. _app-taskqueue-job:

Configuration
~~~~~~~~~~~~~~~~
A :class:`TaskQueue` accepts several configuration parameters on top of the
standard :ref:`application settings <settings>`:

.. _app-tasks_path:

* The :ref:`task_paths <setting-task_paths>` parameter specify
  a list of python paths where to collect :class:`models.Job` classes::
  
      task_paths = ['myjobs','another.moduledir.*']
      
  The ``*`` at the end of the second module indicates to collect
  :class:`models.Job` from all submodules of ``another.moduledir``.
  
* The :ref:`schedule_periodic <setting-schedule_periodic>` flag indicates
  if the :class:`TaskQueue` can schedule :class:`models.PeriodicJob`. Usually,
  only one running :class:`TaskQueue` application is responsible for
  scheduling tasks while all the other, simply consume tasks.
  This parameter can also be specified in the command line via the
  ``--schedule-periodic`` flag. Default: ``False``.
  
* The :ref:`task_backend <setting-task_backend>` parameter is a url
  type string which specifies the :class:`backends.TaskBackend`
  to use.


.. _app-taskqueue-app:

Task queue application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: TaskQueue
   :members:
   :member-order: bysource
   

.. _celery: http://celeryproject.org/
'''
import os
from datetime import datetime

import pulsar
from pulsar import to_string, command
from pulsar.utils.log import local_property
from pulsar.utils.config import section_docs

from .models import *
from .states import *
from .backends import *
from .rpc import *


section_docs['Task Consumer'] = '''
This section covers configuration parameters used by CPU bound type applications
such as the :ref:`distributed task queue <apps-taskqueue>` and the
:ref:`test suite <apps-test>`.'''


class TaskSetting(pulsar.Setting):
    virtual = True
    app = 'tasks'
    section = "Task Consumer"


class TaskBackend(TaskSetting):
    name = "task_backend"
    flags = ["--task-backend"]
    default = "local://"
    desc = '''\
        Task backend.

        A task backend is string which connect to the backend storing Tasks)
        which accepts one parameter only and returns an instance of a
        distributed queue which has the same API as
        :class:`pulsar.MessageQueue`. The only parameter passed to the
        task queue factory is a :class:`pulsar.utils.config.Config` instance.
        This parameters is used by :class:`pulsar.apps.tasks.TaskQueue`
        application.'''

    
class TaskPaths(TaskSetting):
    name = "task_paths"
    validator = pulsar.validate_list
    default = []
    desc = """\
        List of python dotted paths where tasks are located.
        
        This parameter can only be specified during initialization or in a
        :ref:`config file <setting-config>`.
        """
        
        
class SchedulePeriodic(TaskSetting):
    name = 'schedule_periodic'
    flags = ["--schedule-periodic"]
    validator = pulsar.validate_bool
    action = "store_true"
    default = False
    desc = '''\
        Enable scheduling of periodic tasks.
        
        If enabled, :class:`pulsar.apps.tasks.PeriodicJob` will produce
        tasks according to their schedule.
        '''


class TaskQueue(pulsar.Application):
    '''A :class:`pulsar.apps.Application` for consuming
task.Tasks and managing scheduling of tasks via a
:class:`scheduler.Scheduler`.'''
    backend = None
    name = 'tasks'
    cfg = pulsar.Config(apps=('tasks',), timeout=600, backlog=5)

    def request_instance(self, request):
        return self.scheduler.get_task(request)
    
    def monitor_start(self, monitor):
        '''When the monitor starts create the :class:`backends.TaskBackend`.'''
        if self.callable:
            self.callable()
        self.backend = getbe(self.cfg.task_backend,
                             name=self.name,
                             task_paths=self.cfg.task_paths,
                             schedule_periodic=self.cfg.schedule_periodic,
                             backlog=self.cfg.backlog)
        
    def monitor_task(self, monitor):
        '''Override the :meth:`pulsar.apps.Application.monitor_task` callback
to check if the :attr:`scheduler` needs to perform a new run.'''
        super(TaskQueue, self).monitor_task(monitor)
        if self.backend and monitor.running:
            if self.backend.next_run <= datetime.now():
                self.backend.tick()

    def worker_start(self, worker):
        self.backend.start(worker)
        
    def worker_stopping(self, worker):
        self.backend.close(worker)
        
    def actorparams(self, monitor, params):
        # Make sure we invoke super function so that we get the distributed
        # task queue
        params = super(TaskQueue, self).actorparams(monitor, params)
        # workers do not schedule periodic tasks
        params['app'].cfg.set('schedule_periodic', False)
        return params
     
    
@command()
def next_scheduled(request, jobnames=None):
    actor = request.actor
    return actor.app.backend.next_scheduled(jobnames)
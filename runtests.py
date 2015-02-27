#!/usr/bin/env python
import sys
import os
from multiprocessing import current_process


def run(**params):
    args = params.get('argv', sys.argv)
    if '--coveralls' in args:
        import pulsar
        from pulsar.utils.path import Path
        from pulsar.apps.test.cov import coveralls

        path = Path(__file__)
        repo_token = None
        strip_dirs = [Path(pulsar.__file__).parent.parent, os.getcwd()]
        if os.path.isfile('.coveralls-repo-token'):
            with open('.coveralls-repo-token') as f:
                repo_token = f.read().strip()
        code = coveralls(strip_dirs=strip_dirs,
                         repo_token=repo_token)
        sys.exit(0)
    # Run the test suite
    if '--coverage' in args:
        import coverage
        p = current_process()
        p._coverage = coverage.coverage(data_suffix=True)
        p._coverage.start()
    runtests(**params)


def runtests(**params):
    import pulsar
    from pulsar.apps.test import TestSuite
    from pulsar.apps.test.plugins import bench, profile
    import pulsar.utils.settings.backend
    djangopath = os.path.join(os.path.dirname(__file__),
                              'examples', 'djchat')
    if djangopath not in sys.path:
        sys.path.append(djangopath)
    #
    TestSuite(description='Pulsar Asynchronous test suite',
              modules=('tests',
                       ('examples', 'tests'),
                       ('examples', 'test_*')),
              plugins=(bench.BenchMark(),
                       profile.Profile()),
              pidfile='test.pid',
              **params).start()


if __name__ == '__main__':
    run()

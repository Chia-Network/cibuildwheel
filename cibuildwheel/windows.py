import os
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple
from glob import glob
from zipfile import ZipFile

from .util import (
    download,
    get_build_verbosity_extra_flags,
    prepare_command,
)


IS_RUNNING_ON_AZURE = os.path.exists('C:\\hostedtoolcache')
IS_RUNNING_ON_TRAVIS = os.environ.get('TRAVIS_OS_NAME') == 'windows'


def shell(args, env=None, cwd=None):
    print('+ ' + ' '.join(args))
    return subprocess.check_call(' '.join(args), env=env, cwd=cwd, shell=True)


def build(project_dir, output_dir, test_command, before_test, test_requires, test_extras, before_build, build_verbosity, build_selector, repair_command, environment):
    abs_project_dir = os.path.abspath(project_dir)
    temp_dir = tempfile.mkdtemp(prefix='cibuildwheel')
    built_wheel_dir = os.path.join(temp_dir, 'built_wheel')
    repaired_wheel_dir = os.path.join(temp_dir, 'repaired_wheel')

    # run the before_build command
    if before_build:
        before_build_prepared = prepare_command(before_build, project=abs_project_dir)
        shell([before_build_prepared])

    # build the wheel
    if os.path.exists(built_wheel_dir):
        shutil.rmtree(built_wheel_dir)
    os.makedirs(built_wheel_dir)
    shell(['pip3', 'wheel', abs_project_dir, '-w', built_wheel_dir, '--no-deps'] + get_build_verbosity_extra_flags(build_verbosity))
    built_wheel = glob(os.path.join(built_wheel_dir, '*.whl'))[0]

    # repair the wheel
    if os.path.exists(repaired_wheel_dir):
        shutil.rmtree(repaired_wheel_dir)
    os.makedirs(repaired_wheel_dir)
    if built_wheel.endswith('none-any.whl') or not repair_command:
        # pure Python wheel or empty repair command
        shutil.move(built_wheel, repaired_wheel_dir)
    else:
        repair_command_prepared = prepare_command(repair_command, wheel=built_wheel, dest_dir=repaired_wheel_dir)
        shell([repair_command_prepared])
    repaired_wheel = glob(os.path.join(repaired_wheel_dir, '*.whl'))[0]

    if test_command:
        # set up a virtual environment to install and test from, to make sure
        # there are no dependencies that were pulled in at build time.
        shell(['pip3', 'install', 'virtualenv'])
        venv_dir = tempfile.mkdtemp()
        shell(['python3', '-m', 'virtualenv', venv_dir])

        virtualenv_env = os.environ.copy()

        venv_script_path = os.path.join(venv_dir, 'Scripts')
        if os.path.exists(os.path.join(venv_dir, 'bin')):
            # pypy2.7 bugfix
            venv_script_path = os.pathsep.join([venv_script_path, os.path.join(venv_dir, 'bin')])
        virtualenv_env['PATH'] = os.pathsep.join([
            venv_script_path,
            virtualenv_env['PATH'],
        ])
        virtualenv_env["__CIBW_VIRTUALENV_PATH__"] = venv_dir

        if before_test:
            before_test_prepared = prepare_command(before_test, project=abs_project_dir)
            shell([before_test_prepared], env=virtualenv_env)

        # install the wheel
        shell(['pip3', 'install', repaired_wheel + test_extras], env=virtualenv_env)

        # test the wheel
        if test_requires:
            shell(['pip3', 'install'] + test_requires, env=virtualenv_env)

        # run the tests from c:\, with an absolute path in the command
        # (this ensures that Python runs the tests against the installed wheel
        # and not the repo code)
        test_command_prepared = prepare_command(test_command, project=abs_project_dir)
        shell([test_command_prepared], cwd='c:\\', env=virtualenv_env)

        # clean up
        shutil.rmtree(venv_dir)

        # we're all done here; move it to output (remove if already exists)
        dst = os.path.join(output_dir, os.path.basename(repaired_wheel))
        if os.path.isfile(dst):
            os.remove(dst)
        shutil.move(repaired_wheel, dst)

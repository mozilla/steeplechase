# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from manifestparser import TestManifest
from mozdevice import DeviceManagerSUT, DMError
from optparse import OptionParser
from mozprofile import FirefoxProfile, Profile, Preferences
from mozprofile.permissions import ServerLocations
from mozhttpd import MozHttpd
from mozhttpd.handlers import json_response
from Queue import Queue

import json
import mozfile
import mozinfo
import mozlog
import moznetwork
import os
import re
import sys
import threading
import uuid

class Options(OptionParser):
    def __init__(self, **kwargs):
        OptionParser.__init__(self, **kwargs)
        usage = """
                Usage instructions for runsteeplechase.py.
                %prog [options] test <test>*
                """
        self.add_option("--binary",
                        action="store", type="string", dest="binary",
                        help="path to application (required)")
        self.add_option("--binary2",
                        action="store", type="string", dest="binary2",
                        help="path to application for client 2. defaults to BINARY")
        self.add_option("--package",
                        action="store", type="string", dest="package",
                        help="path to application package (either this or --binary required")
        self.add_option("--package2",
                        action="store", type="string", dest="package2",
                        help="path to application package for client 2. defaults to PACKAGE")
        self.add_option("--html-manifest",
                        action="store", type="string", dest="html_manifest",
                        help="Manifest of HTML tests to run")
        self.add_option("--specialpowers-path",
                        action="store", type="string", dest="specialpowers",
                        help="path to specialpowers extension (required)")
        self.add_option("--prefs-file",
                        action="store", type="string", dest="prefs",
                        help="path to testing preferences file")
        self.add_option("--host1",
                        action="store", type="string", dest="host1",
                        help="first remote host to run tests on")
        self.add_option("--host2",
                        action="store", type="string", dest="host2",
                        help="first remote host to run tests on")
        self.add_option("--signalling-server",
                        action="store", type="string", dest="signalling_server",
                        help="signalling server URL to use for tests")
        self.add_option("--noSetup",
                        action="store_false", dest="setup",
                        default="True",
                        help="do not copy files to device")
        self.add_option("--remote-webserver",
                        action="store", type="string", dest="remote_webserver",
                        help="ip address to use for webserver")
        self.add_option("--x-display",
                        action="store", type="string", dest="remote_xdisplay",
                        default=":0", help="x display to use on remote system")
        self.add_option("--save-logs-to",
                        action="store", type="string", dest="log_dest",
                        help="save client logs to this directory")

        self.set_usage(usage)

def get_results(output):
    """Count test passes/failures in output.
    Return (passes, failures)."""
    passes, failures = 0, 0
    for line_string in output.splitlines():
        try:
            line_object = json.loads(line_string)
            if not isinstance(line_object, dict):
                continue
            if line_object["action"] == "test_unexpected_fail":
                failures += 1
            elif line_object["action"] == "test_pass":
                passes += 1
        except ValueError:
            pass
    return passes, failures

class RunThread(threading.Thread):
    def __init__(self, args=(), **kwargs):
        threading.Thread.__init__(self, args=args, **kwargs)
        self.name = kwargs.get("name", "Thread")
        self.args = args

    def run(self):
        dm, cmd, env, cond, results = self.args
        result = None
        output = None
        try:
            output = dm.shellCheckOutput(cmd, env=env)
            result = get_results(output)
        except DMError as e:
            output = "Error running build: " + e.msg
            result = 0, 1
        finally:
            #TODO: actual result
            cond.acquire()
            results.append((self, result, output))
            cond.notify()
            cond.release()
            del self.args

class ApplicationAsset(object):
    def __init__(self, path, remote_path, log, dm):
        self.path = path
        self.remote_path = remote_path
        self.log = log
        self.dm = dm

    def setup_client(self):
        raise NotImplementedError('Implement setup_client()')

    def path_to_launch(self):
        raise NotImplementedError('Implement path_to_launch()')

class Binary(ApplicationAsset):
# Note that the legacy --binary gives the full path to the core firefox binary. This does not work on MacOS (now),
# but is great for Linux and Windows.

    def setup_client(self):
        self.log.debug("Pushing %s to %s..." % (self.path, self.remote_path))
        self.dm.mkDir(self.remote_path)
        self.dm.pushDir(os.path.dirname(self.path), self.remote_path)

    def path_to_launch(self):
        app = os.path.basename(self.path)
        return os.path.join(self.remote_path, app)

class Package(ApplicationAsset):

    def archive_name(self):
        return os.path.basename(self.path)

    def remote_archive_name(self):
        return os.path.join(self.remote_path, self.archive_name())

    def push(self):
        self.log.debug("Pushing %s to %s..." % (self.path, self.remote_path))
        self.dm.mkDir(self.remote_path)
        self.dm.pushFile(self.path, self.remote_archive_name())

    def setup_client(self):
        self.push()
        self.unpack()

    def unpack(self):
        raise NotImplementedError('Implement unpack()')

class TarBz2(Package):

    def unpack(self):
        cmd = ['cd', self.remote_path, ';', 'tar', 'xjf', self.remote_archive_name()]
        self.log.debug("Running %s on remote host.." % cmd)
        output = self.dm.shellCheckOutput(cmd, env=None)

    def path_to_launch(self):
        return os.path.join(self.remote_path, 'firefox', 'firefox')

class Zip(Package):

    def unpack(self):
        cmd = ['unzip', '-u', '-o', '-d', self.remote_path, self.remote_archive_name()]
        self.log.debug("Running %s on remote host.." % cmd)
        output = self.dm.shellCheckOutput(cmd, env=None)

    def path_to_launch(self):
        return os.path.join(self.remote_path, 'firefox', 'firefox.exe')

class Dmg(Package):

    def unpack(self):
        umount_cmd = ['umount', '/Volumes/Steeplechase']
        self.log.debug("Running %s on remote host.." % umount_cmd)
        try:
            output = self.dm.shellCheckOutput(umount_cmd, env=None)
        except Exception as ex:
            self.log.debug("EXPECTED: umount failed with %s" % ex)
        cmd = ['hdiutil', 'attach', '-quiet', '-mountpoint', '/Volumes/Steeplechase', self.remote_archive_name()]
        self.log.debug("Running %s on remote host.." % cmd)
        output = self.dm.shellCheckOutput(cmd, env=None)
        cmd = ['cp', '-r', '/Volumes/Steeplechase/*.app', os.path.join(self.remote_path, 'firefox.app')]
        self.log.debug("Running %s on remote host.." % cmd)
        output = self.dm.shellCheckOutput(cmd, env=None)
        self.log.debug("Running %s on remote host.." % umount_cmd)
        output = self.dm.shellCheckOutput(umount_cmd, env=None)

    def path_to_launch(self):
        return os.path.join(self.remote_path, 'firefox.app', 'Contents', 'MacOS', 'firefox')

def generate_package_asset(path, remote_path, log, dm):
    asset = None
    base, ext = os.path.splitext(path)
    if ext == '.zip':
        asset = Zip(path, remote_path, log, dm)
    elif ext == '.dmg':
        asset = Dmg(path, remote_path, log, dm)
    elif ext == '.bz2':
        real_base, ext2 = os.path.splitext(base)
        if ext2 == ".tar":
            asset = TarBz2(path, remote_path, log, dm)
    return asset

class HTMLTests(object):
    def __init__(self, httpd, remote_info, log, options):
        self.remote_info = remote_info
        self.log = log
        self.options = options
        self.httpd = httpd

    def run(self):
        if self.options.remote_webserver:
            httpd_host = self.options.remote_webserver.split(':')[0]
        else:
            httpd_host = self.httpd.host
        httpd_port = self.httpd.httpd.server_port

        locations = ServerLocations()
        locations.add_host(host=httpd_host,
                           port=httpd_port,
                           options='primary,privileged')

        #TODO: use Preferences.read when prefs_general.js has been updated
        prefpath = self.options.prefs
        prefs = {}
        prefs.update(Preferences.read_prefs(prefpath))
        interpolation = { "server": "%s:%d" % (httpd_host, httpd_port),
                          "OOP": "false"}
        prefs = json.loads(json.dumps(prefs) % interpolation)
        for pref in prefs:
          prefs[pref] = Preferences.cast(prefs[pref])
        prefs["steeplechase.signalling_server"] = self.options.signalling_server
        prefs["steeplechase.signalling_room"] = str(uuid.uuid4())
        prefs["media.navigator.permission.disabled"] = True

        specialpowers_path = self.options.specialpowers
        threads = []
        results = []
        cond = threading.Condition()
        for info in self.remote_info:
            with mozfile.TemporaryDirectory() as profile_path:
                # Create and push profile
                print "Writing profile for %s..." % info['name']
                prefs["steeplechase.is_initiator"] = info['is_initiator']
                profile = FirefoxProfile(profile=profile_path,
                                         preferences=prefs,
                                         addons=[specialpowers_path],
                                         locations=locations)
                print "Pushing profile to %s..." % info['name']
                remote_profile_path = os.path.join(info['test_root'], "profile")
                info['dm'].mkDir(remote_profile_path)
                info['dm'].pushDir(profile_path, remote_profile_path)
                info['remote_profile_path'] = remote_profile_path

            env = {}
            env["MOZ_CRASHREPORTER_NO_REPORT"] = "1"
            env["XPCOM_DEBUG_BREAK"] = "warn"
            env["DISPLAY"] = self.options.remote_xdisplay

            cmd = [info['remote_app_path'], "-no-remote",
                   "-profile", info['remote_profile_path'],
                   'http://%s:%d/index.html' % (httpd_host, httpd_port)]
            print "cmd: %s" % (cmd, )
            t = RunThread(name=info['name'],
                          args=(info['dm'], cmd, env, cond, results))
            threads.append(t)

        for t in threads:
            t.start()

        self.log.info("Waiting for results...")
        pass_count, fail_count = 0, 0
        outputs = {}
        while threads:
            cond.acquire()
            while not results:
                cond.wait()
            thread, result, output = results.pop(0)
            cond.release()
            outputs[thread.name] = output
            passes, failures = result
            #XXX: double-counting tests from both clients. Ok?
            pass_count += passes
            fail_count += failures
            if failures:
                self.log.error("Error in %s" % thread.name)
            threads.remove(thread)
        self.log.info("All clients finished")
        for info in self.remote_info:
            if self.options.log_dest:
                with open(os.path.join(self.options.log_dest,
                                       "%s.log" % info['name']), "wb") as f:
                    f.write(outputs[info['name']])
            if fail_count:
                self.log.info("Log output for %s:", info["name"])
                self.log.info(">>>>>>>")
                for line in outputs[info['name']].splitlines():
                    #TODO: make structured log messages human-readable
                    self.log.info(line)
                self.log.info("<<<<<<<")
        return pass_count, fail_count

def main(args):
    parser = Options()
    options, args = parser.parse_args()
    if not options.html_manifest or not options.specialpowers or not options.host1 or not options.host2 or not options.signalling_server:
        parser.print_usage()
        return 2

    if not options.binary and not options.package:
        parser.print_usage()
        return 2

    if options.binary and options.package:
        parser.print_usage()
        return 2

    if options.binary:
        if not options.binary2 and not options.package2:
            options.binary2 = options.binary

    if options.package:
        if not options.binary2 and not options.package2:
            options.package2 = options.package

    if options.binary:
        if not os.path.isfile(options.binary):
            parser.error("Binary %s does not exist" % options.binary)
            return 2

    if options.binary2:
        if not os.path.isfile(options.binary2):
            parser.error("Binary %s does not exist" % options.binary2)
            return 2

    if options.package:
        if not os.path.isfile(options.package):
            parser.error("Package %s does not exist" % options.package)
            return 2

    if options.package2:
        if not os.path.isfile(options.package2):
            parser.error("Package %s does not exist# % options.package2")
            return 2

    if not os.path.isdir(options.specialpowers):
        parser.error("SpecialPowers directory %s does not exist" % options.specialpowers)
        return 2
    if options.prefs and not os.path.isfile(options.prefs):
        parser.error("Prefs file %s does not exist" % options.prefs)
        return 2
    if options.log_dest and not os.path.isdir(options.log_dest):
        parser.error("Log directory %s does not exist" % options.log_dest)
        return 2

    log = mozlog.getLogger('steeplechase')
    log.setLevel(mozlog.DEBUG)
    if ':' in options.host1:
        host, port = options.host1.split(':')
        dm1 = DeviceManagerSUT(host, port)
    else:
        dm1 = DeviceManagerSUT(options.host1)
    if ':' in options.host2:
        host, port = options.host2.split(':')
        dm2 = DeviceManagerSUT(host, port)
    else:
        dm2 = DeviceManagerSUT(options.host2)
    remote_info = [{'dm': dm1,
                    'binary': options.binary,
                    'package': options.package,
                    'is_initiator': True,
                    'name': 'Client 1'},
                   {'dm': dm2,
                    'binary': options.binary2,
                    'package': options.package2,
                    'is_initiator': False,
                    'name': 'Client 2'}]
    # first, push app
    for info in remote_info:
        dm = info['dm']
        test_root = os.path.join(dm.getDeviceRoot(), "steeplechase")
        remote_app_dir = os.path.join(test_root, "app")

        if options.setup:
            if dm.dirExists(test_root):
                dm.removeDir(test_root)
            dm.mkDir(test_root)
        info['test_root'] = test_root

        if info['binary']:
            asset = Binary(path=info['binary'], remote_path=remote_app_dir, log=log, dm=info['dm'])
        else:
            asset = generate_package_asset(path=info['package'], remote_path=remote_app_dir, log=log, dm=info['dm'])

        if options.setup:
            log.info("Pushing app to %s...", info["name"])
            asset.setup_client()
        info['remote_app_path'] = asset.path_to_launch()
        if not options.setup and not dm.fileExists(info['remote_app_path']):
            log.error("App does not exist on %s, don't use --noSetup", info['name'])
            return 2

    pass_count, fail_count = 0, 0
    if options.html_manifest:
        manifest = TestManifest(strict=False)
        manifest.read(options.html_manifest)
        manifest_data = {"tests": [{"path": t["relpath"]} for t in manifest.active_tests(disabled=False, **mozinfo.info)]}

        remote_port = 0
        if options.remote_webserver:
            result = re.search(':(\d+)', options.remote_webserver)
            if result:
                remote_port = int(result.groups()[0])


        @json_response
        def get_manifest(req):
            return (200, manifest_data)
        handlers = [{
            'method': 'GET',
            'path': '/manifest.json',
            'function': get_manifest
            }]
        httpd = MozHttpd(host=moznetwork.get_ip(), port=remote_port, log_requests=True,
                         docroot=os.path.join(os.path.dirname(__file__), "..", "webharness"),
                         urlhandlers=handlers,
                         path_mappings={"/tests": os.path.dirname(options.html_manifest)})
        httpd.start(block=False)
        test = HTMLTests(httpd, remote_info, log, options)
        html_pass_count, html_fail_count = test.run()
        pass_count += html_pass_count
        fail_count += html_fail_count
        httpd.stop()
    log.info("Result summary:")
    log.info("Passed: %d" % pass_count)
    log.info("Failed: %d" % fail_count)
    return fail_count == 0

if __name__ == '__main__':
    sys.exit(0 if main(sys.argv[1:]) else 1)

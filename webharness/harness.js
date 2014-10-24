var tests = [];
var current_test = -1;
var current_window = null;
var socket;
var socket_messages = [];
var socket_message_deferreds = [];
var is_initiator = SpecialPowers.getBoolPref("steeplechase.is_initiator");

function fetch_manifest() {
  var deferred = Q.defer();
  // Load test manifest
  var req = new XMLHttpRequest();
  req.open("GET", "/manifest.json", true);
  req.responseType = "json";
  req.overrideMimeType("application/json");
  req.onload = function() {
    if (req.readyState == 4) {
      if (req.status == 200) {
        deferred.resolve(req.response);
      } else {
        deferred.reject(new Error("Error fetching test manifest"));
      }
    }
  };
  req.onerror = function() {
    deferred.reject(new Error("Error fetching test manifest"));
  };
  req.send(null);
  return deferred.promise;
}

function load_script(script) {
  var deferred = Q.defer();
  var s = document.createElement("script");
  s.src = script;
  s.onload = function() {
    deferred.resolve(s);
  };
  s.onerror = function() {
    deferred.reject(new Error("Error loading: " + script));
  };
  document.head.appendChild(s);
  return deferred.promise;
}

/*
 * Receive a single message from |socket|. If
 * there is a deferred (from wait_for_message)
 * waiting on it, resolve that deferred. Otherwise
 * queue the message for a future waiter.
 */
function socket_message(data) {
  var message = JSON.parse(data);
  if (socket_message_deferreds.length > 0) {
    var d = socket_message_deferreds.shift();
    d.resolve(message);
  } else {
    socket_messages.push(message);
  }
}

/*
 * Return a promise for the next available message
 * to come in on |socket|. If there is a queued
 * message, resolves the promise immediately, otherwise
 * waits for socket_message to receive one.
 */
function wait_for_message() {
  var deferred = Q.defer();
  if (socket_messages.length > 0) {
    deferred.resolve(socket_messages.shift());
  } else {
    socket_message_deferreds.push(deferred);
  }
  return deferred.promise;
}

/*
 * Send an object as a message on |socket|.
 */
function send_message(data) {
  socket.send(JSON.stringify(data));
}

function connect_socket() {
  var server = SpecialPowers.getCharPref("steeplechase.signalling_server");
  if (server.substr(server.length - 1) != "/") {
    server += "/";
  }
  var room = SpecialPowers.getCharPref("steeplechase.signalling_room");
  var script = server + "socket.io/socket.io.js";
  return load_script(script).then(function() {
    var deferred = Q.defer();
    socket = io.connect(server + "?room=" + room);
    socket.on("connect", function() {
      socket.on("message", socket_message);
      deferred.resolve(socket);
    });
    socket.on("error", function() {
      deferred.reject(new Error("socket.io error"));
    });
    socket.on("connect_failed", function() {
      deferred.reject(new Error("socket failed to connect"));
    });
    return deferred;
  }).then(function () {
    var deferred = Q.defer();
    socket.once("numclients", function(data) {
      if (data.clients == 2) {
        // Other side is already there.
        deferred.resolve(socket);
      } else if (data.clients > 2) {
        deferred.reject(new Error("Too many clients connected"));
      } else {
        // Just us, wait for the other side.
        socket.once("client_joined", function() {
          deferred.resolve(socket);
        });
      }
    });
    return deferred.promise;
  });
}

Q.all([fetch_manifest(),
       connect_socket()]).then(run_tests,
                               harness_error);

function run_tests(results) {
  var manifest = results[0];
  // Manifest looks like:
  // {'tests': [{'path': '...'}, ...]}
  tests = manifest.tests;
  run_next_test();
}

function run_next_test() {
  ++current_test;
  if (current_test >= tests.length) {
    finish();
    return;
  }

  var path = tests[current_test].path;
  try {
    current_window = window.open("/tests/" + path);
  } catch(ex) {
    harness_error(ex);
    return;
  }
  current_window.addEventListener("error", harness_error);
  current_window.addEventListener("load", function() {
    dump("loaded " + path + "\n");
    send_message({"action": "test_loaded", "test": path});
    // Wait for other side to have loaded this test.
    wait_for_message().then(function (m) {
      if (m.action != "test_loaded") {
        //XXX: should this be fatal?
        harness_error(new Error("Looking for test_loaded, got: " + JSON.stringify(m)));
        return;
      }
      if (m.test != path) {
        harness_error(new Error("Wrong test loaded on other side: " + m.test));
        return;
      }
      current_window.run_test(is_initiator);
    });
  });
  //TODO: timeout handling
}

function harness_error(error) {
  log_result(false, error.message, "harness");
  var stack = error.stack || error.error || new Error().stack;
  dump(stack +"\n");
  finish();
}
addEventListener("error", harness_error);

// Called by tests via test.js.
function test_finished() {
  current_window.close();
  current_window = null;
  setTimeout(run_next_test, 0);
}

function finish() {
  SpecialPowers.quit();
}

function log(message, test, extra) {
  //TODO: make this structured?
  dump(message + "\n");
}

function log_result(result, message, test) {
  var output = {'action': result ? "test_pass" : "test_unexpected_fail",
                'message': message,
                'time': Date.now(),
                'source_file': test || tests[current_test].path};
  dump(JSON.stringify(output) + "\n");
}

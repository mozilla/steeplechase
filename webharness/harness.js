var tests = [];
var current_test = -1;
var current_window = null;
var socket;
var socket_messages_admin = [];
var socket_messages_test = [];
var socket_message_promises_admin = [];
var socket_message_promises_test = [];
var is_initiator = SpecialPowers.getBoolPref("steeplechase.is_initiator");
var timeout = SpecialPowers.getIntPref("steeplechase.timeout");
var adminroom = SpecialPowers.getCharPref("steeplechase.signalling_room");
var loadedscripts = {};
var testroom;

function fetch_manifest() {
  return new Promise((resolve, reject) => {
    // Load test manifest
    var req = new XMLHttpRequest();
    req.open("GET", "/manifest.json", true);
    req.responseType = "json";
    req.overrideMimeType("application/json");
    req.onload = function() {
      if (req.readyState == 4) {
        if (req.status == 200) {
          resolve(req.response);
        } else {
          reject(new Error("Error fetching test manifest"));
        }
      }
    };
    req.onerror = function() {
      reject(new Error("Error fetching test manifest"));
    };
    req.send(null);
  });
}

function load_script(script) {
  return new Promise((resolve, reject) => {
    if ((script in loadedscripts)) {
      resolve(loadedscripts[script]);
    }
    else {
      var s = document.createElement("script");
      s.src = script;
      s.onload = function() {
        loadedscripts[script] = s; 
        resolve(s);
      };
      s.onerror = function() {
        reject(new Error("Error loading: " + script));
      };
      document.head.appendChild(s);
    }
  });
}

/*
 * Receive a single message from |socket|. If
 * there is a deferred (from wait_for_message)
 * waiting on it, resolve that deferred. Otherwise
 * queue the message for a future waiter.
 */
function socket_message(socket_messages,socket_message_promises,data) {
  var message = JSON.parse(data);
  if (socket_message_promises.length > 0) {
    var res = socket_message_promises.shift();
    res(message);
  } else {
    socket_messages.push(message);
  }
}

/*
 *  Wrapper around socket_message for test related messaging
 */
function socket_message_test(data) {
  return socket_message(socket_messages_test,socket_message_promises_test,data);
}

/*
 * Wrapper around socket_message for admin related messaging
 */
function socket_message_admin(data){
  return socket_message(socket_messages_admin,socket_message_promises_admin,data);
}

/*
 * Return a promise for the next available message
 * to come in on |socket|. If there is a queued
 * message, resolves the promise immediately, otherwise
 * waits for socket_message to receive one.
 */
function wait_for_message(socket_messages,socket_message_promises) {
  return new Promise(resolve => {
    if (socket_messages.length > 0) {
      resolve(socket_messages.shift());
    } else {
      socket_message_promises.push(resolve);
    }
  });
}

/*
 * Return a promise for the next available message
 * to come in on |socket|. If there is a queued
 * message, resolves the promise immediately, otherwise
 * waits for socket_message to receive one.
 */
function wait_for_admin_message() {
  return wait_for_message(socket_messages_admin,socket_message_promises_admin);
}

/*
 * Return a promise for the next available message
 * to come in on |socket|. If there is a queued
 * message, resolves the promise immediately, otherwise
 * waits for socket_message to receive one.
 */
function wait_for_test_message() {
  return wait_for_message(socket_messages_test,socket_message_promises_test);
}

/*
 * This methods sends a message to the socket server with the information to 
 * broadcast to all clients in that room.
 */
function send_message(room_to_send,data) {
	socket.emit('message_to_server', JSON.stringify({room: room_to_send, msg: JSON.stringify(data)}));
}

/*
* Send an object as an admin message on |socket|.
*/
function send_admin_message(data) {
  send_message(adminroom,data);
}

/*
* Send an object as a test message on |socket|.
*/
function send_test_message(data) {
  send_message(testroom,data);
}


function connect_socket(type) {
  var server = SpecialPowers.getCharPref("steeplechase.signalling_server");
  if (server.substr(server.length - 1) != "/") {
    server += "/";
  }
  var script = server + "socket.io/socket.io.js";
  return load_script(script).then(function() {
    return new Promise((resolve, reject) => {
      if (type == "test") {
          testroom = adminroom+tests[current_test].path;
          socket.emit('subscribe', testroom);
      } else {
        socket = io.connect(server);
        socket.emit('subscribe', adminroom);
        socket.on("message", function(data_string){
          data_full = JSON.parse(data_string);
          if ( data_full.room === testroom){
            socket_message_test(JSON.stringify(data_full.msg));
          } else if (data_full.room === adminroom){
            socket_message_admin(JSON.stringify(data_full.msg));
          } else {
            reject(new Error("Unrecognized room: "+JSON.stringify(data_full.msg)));
          }
        }); 
      }
      socket.on('subscribed', function(data) {
        resolve(socket);
      });
      socket.on("error", function() {
        reject(new Error("socket.io error"));
      });
      socket.on("connect_failed", function() {
        reject(new Error("socket failed to connect"));
      });
    });
  }).then(function () {
    return new Promise((resolve, reject) => {
      socket.once("numclients", function(data) {
        if (data.clients == 2) {
          // Other side is already there.
          resolve(socket);
        } else if (data.clients > 2) {
          reject(new Error("Too many clients connected"));
        } else {
          // Just us, wait for the other side.
          socket.once("client_joined", function() {
            resolve(socket);
          });
        }
      });
    });
  });
}

Promise.all([fetch_manifest(),
             connect_socket("administration")]).then(run_tests,
                                     harness_error);

function run_tests(results) {
  var manifest = results[0];
  // Manifest looks like:
  // {'tests': [{'path': '...'}, ...]}
  tests = manifest.tests;
  run_next_test();
}

function test_error(errorMsg, url, lineNumber) {
  log_result(false, errorMsg + " @" + url + ":" + lineNumber, tests[current_test].path);
  finish();
}

function run_next_test() {
  ++current_test;
  if (current_test >= tests.length) {
    finish();
    return;
  }
  var room_ready = connect_socket("test");
  room_ready.then(()=>{
    var path = tests[current_test].path;
    try {
      current_window = window.open("/tests/" + path);
    } catch(ex) {
      harness_error(ex);
      return;
    }
    current_window.onerror = test_error;
    current_window.addEventListener("load", function() {
      dump("loaded " + path + "\n");
      send_admin_message({"action": "test_loaded", "test": path});
      // Wait for other side to have loaded this test.
      wait_for_admin_message().then(function (m) {
        if (m.action != "test_loaded") {
          //XXX: should this be fatal?
          harness_error(new Error("Looking for test_loaded, got: " + JSON.stringify(m)));
          return;
        }
        if (m.test != path) {
          harness_error(new Error("Wrong test loaded on other side: " + JSON.stringify(m.test)));
          return;
        }
        current_window.run_test(is_initiator,timeout);
      });
    });
  });
  //TODO: timeout handling
}

function harness_error(error) {
  log_result(false, error.message, "harness.js");
  var stack = error.stack || error.error || new Error().stack;
  dump(stack +"\n");
  finish();
}
addEventListener("error", harness_error);

// Called by tests via test.js.
function test_finished() {
  socket.emit('unsubscribe', testroom);
  current_window.close();
  current_window = null;
  setTimeout(run_next_test, 0);
}

function finish() {
  SpecialPowers.quit();
}

function log(message, test, extra) {
  //TODO: make this structured?
  console.log(message);
  dump(message + "\n");
}

function log_result(result, message, test) {
  var output = {'action': result ? "test_pass" : "test_unexpected_fail",
                'message': message,
                'time': Date.now(),
                'source_file': test || tests[current_test].path};
  console.log(JSON.stringify(output));
  dump(JSON.stringify(output) + "\n");
}

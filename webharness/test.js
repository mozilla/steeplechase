var log_result = window.opener.log_result;
var info = window.opener.log;
var pass_count = 0;
var fail_count = 0;

function ok(condition, message) {
  log_result(!!condition, message);
}

function is(a, b, message) {
  ok(a == b, message);
}

function isnot(a, b, message) {
  ok(a != b, message);
}

function todo(condition, message) {
  // Just ignore these.
}

function finish() {
  window.opener.test_finished();
}

var wait_for_message = window.opener.wait_for_message;
var send_message = window.opener.send_message;

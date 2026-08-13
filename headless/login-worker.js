'use strict';

// Task 10 defines only the credential-free local protocol. Task 11 supplies
// the bounded browser flow; credentials will be read inside this worker.
const PROTOCOL_VERSION = 1;
const REQUEST_KEYS = new Set(['version', 'action', 'request_id', 'challenge']);

function validIdentifier(value) {
  return typeof value === 'string' && value.length > 0 && value.length <= 128 && !/\s/.test(value);
}

function parseRequest(line) {
  const request = JSON.parse(line);
  if (!request || typeof request !== 'object' || Array.isArray(request)) throw new Error('invalid request');
  if (Object.keys(request).some(key => !REQUEST_KEYS.has(key))) throw new Error('unsupported request field');
  if (request.version !== PROTOCOL_VERSION || request.action !== 'start') throw new Error('unsupported request');
  if (!validIdentifier(request.request_id) || !validIdentifier(request.challenge)) throw new Error('invalid request');
  return request;
}

function emit(request, state, code) {
  const event = {
    version: PROTOCOL_VERSION,
    request_id: request.request_id,
    challenge: request.challenge,
    state,
  };
  if (code) event.code = code;
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  input += chunk;
  if (Buffer.byteLength(input, 'utf8') > 4096) process.exit(2);
});
process.stdin.on('end', () => {
  try {
    const line = input.split(/\r?\n/, 1)[0];
    const request = parseRequest(line);
    emit(request, 'started');
    emit(request, 'failed', 'not_implemented');
  } catch {
    process.exitCode = 2;
  }
});

module.exports = { parseRequest, emit };

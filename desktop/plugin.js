// hermes-xai (voice module) — full-duplex xAI Grok Voice in the Hermes Desktop composer.
//
// Uncompiled ESM, one file: the loader resolves only @hermes/plugin-sdk and react, so every
// element goes through createElement. The xAI key never reaches this window: the backend half
// (`dashboard/plugin_api.py`) mints a 300 s client secret, and this file opens
// wss://api.x.ai/v1/realtime with it as the `xai-client-secret.<value>` subprotocol.
//
// Delegation: the voice model has two tools. `hermes_task` becomes a normal `prompt.submit` on the
// open chat (surface `voice-live`, the same seam GPT-Live uses), and the turn's
// `message.complete` text goes back to the voice as a "[Hermes result]" message it says aloud.
import { host, icons } from '@hermes/plugin-sdk'
import { createElement as h, useEffect, useState } from 'react'

const RATE = 24000
const CONTEXT_TURNS = 12

const WORKLET = `
class Pcm24k extends AudioWorkletProcessor {
  process (inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch && ch.length) this.port.postMessage(ch.slice(0))
    return true
  }
}
registerProcessor('hermes-xai-pcm', Pcm24k)
`

function toBase64 (float32) {
  const pcm = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]))
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  const bytes = new Uint8Array(pcm.buffer)
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000))
  return btoa(bin)
}

function fromBase64 (text) {
  const bin = atob(text)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Int16Array(bytes.buffer, 0, bytes.length >> 1)
}

async function startMic (onFrame) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { autoGainControl: true, echoCancellation: true, noiseSuppression: true }
  })
  // A 24 kHz context makes Chromium resample the mic to the rate xAI expects.
  const context = new AudioContext({ sampleRate: RATE })
  const url = URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' }))
  await context.audioWorklet.addModule(url)
  URL.revokeObjectURL(url)
  const node = new AudioWorkletNode(context, 'hermes-xai-pcm')
  let pending = []
  let size = 0
  node.port.onmessage = ({ data }) => {
    pending.push(data)
    size += data.length
    if (size < RATE / 10) return // ~100 ms per append, as the docs recommend
    const frame = new Float32Array(size)
    let at = 0
    for (const part of pending) { frame.set(part, at); at += part.length }
    pending = []
    size = 0
    onFrame(frame)
  }
  context.createMediaStreamSource(stream).connect(node)
  return () => {
    stream.getTracks().forEach(t => t.stop())
    void context.close().catch(() => {})
  }
}

function createPlayer () {
  const context = new AudioContext({ sampleRate: RATE })
  let next = 0
  const live = new Set()
  return {
    play (pcm) {
      const buffer = context.createBuffer(1, pcm.length, RATE)
      const ch = buffer.getChannelData(0)
      for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000
      const node = context.createBufferSource()
      node.buffer = buffer
      node.connect(context.destination)
      next = Math.max(next, context.currentTime)
      node.start(next)
      next += buffer.duration
      live.add(node)
      node.onended = () => live.delete(node)
    },
    flush () {
      live.forEach(n => { try { n.stop() } catch { /* already ended */ } })
      live.clear()
      next = 0
    },
    close () { this.flush(); void context.close().catch(() => {}) }
  }
}

// One call at module scope: a composer row remounts on navigation, the call must not.
const call = {
  state: 'idle', detail: '', ws: null, stopMic: null, player: null, sessionId: null,
  responding: false, spoke: false, owedTurn: false, hangUp: false, results: [], turns: [],
  delegations: 0, listeners: new Set()
}
const publish = () => call.listeners.forEach(fn => fn())

function send (event) {
  if (call.ws && call.ws.readyState === WebSocket.OPEN) call.ws.send(JSON.stringify(event))
}

function remember (role, text) {
  const t = String(text || '').trim()
  if (!t) return
  call.turns.push(`${role}: ${t}`)
  if (call.turns.length > CONTEXT_TURNS) call.turns.splice(0, call.turns.length - CONTEXT_TURNS)
}

function tearDown (note) {
  const ws = call.ws
  call.ws = null
  if (ws) { try { ws.close() } catch { /* closed */ } }
  if (call.stopMic) { call.stopMic(); call.stopMic = null }
  call.player?.flush()
  Object.assign(call, { state: 'idle', responding: false, spoke: false, owedTurn: false, hangUp: false, results: [], delegations: 0 })
  if (note !== undefined) call.detail = note
  publish()
}

function flushResults () {
  if (!call.results.length || call.responding || !call.ws) return
  const text = call.results.join('\n\n')
  call.results = []
  send({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [{ type: 'input_text', text: `[Hermes result] ${text}` }] } })
  send({ type: 'response.create' })
  call.responding = true
}

async function delegate (request) {
  const sid = call.sessionId
  if (!sid) {
    call.results.push('No chat is open, so the task could not be started.')
    return
  }
  call.delegations += 1
  publish()
  try {
    await host.request('prompt.submit', { session_id: sid, text: request, surface: 'voice-live', voice_context: call.turns.join('\n') })
  } catch (error) {
    call.delegations = Math.max(0, call.delegations - 1)
    call.results.push(`The task failed to start: ${error && error.message ? error.message : String(error)}`)
    flushResults()
    publish()
  }
}

function onTool (name, callId, rawArgs) {
  let args = {}
  try { args = JSON.parse(rawArgs || '{}') } catch { /* unreadable */ }
  let output = { ok: true }
  if (name === 'hermes_task') {
    const request = String(args.request || '').trim()
    if (request) void delegate(request)
    output = { receipt: 'started', note: 'The result will arrive in a "[Hermes result]" message.' }
    call.owedTurn = true
  } else if (name === 'end_call') {
    call.hangUp = true
  } else {
    output = { ok: false, error: 'unknown tool' }
  }
  send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: callId, output: JSON.stringify(output) } })
}

function receive ({ data }) {
  let e
  try { e = JSON.parse(data) } catch { return }
  switch (e.type) {
    case 'input_audio_buffer.speech_started':
      call.player?.flush()
      break
    case 'response.created':
      call.responding = true
      call.spoke = false
      break
    case 'response.output_audio.delta':
    case 'response.audio.delta':
      if (e.delta) { call.spoke = true; call.player?.play(fromBase64(e.delta)) }
      break
    case 'conversation.item.input_audio_transcription.completed':
      remember('user', e.transcript)
      break
    case 'response.output_audio_transcript.done':
      remember('assistant', e.transcript)
      break
    case 'response.function_call_arguments.done':
      onTool(String(e.name || ''), String(e.call_id || ''), String(e.arguments || '{}'))
      break
    case 'response.done':
      call.responding = false
      if (call.hangUp) { window.setTimeout(() => tearDown(''), 1500); break }
      // Ask for a spoken acknowledgement only when the tool-calling response said nothing.
      if (call.owedTurn && !call.spoke && !call.results.length) { send({ type: 'response.create' }); call.responding = true }
      call.owedTurn = false
      flushResults()
      break
    case 'error':
      call.detail = (e.error && e.error.message) || 'Grok Voice error'
      publish()
      break
  }
}

async function start (ctx) {
  if (call.state !== 'idle') return
  call.state = 'connecting'
  call.detail = ''
  call.turns = []
  call.sessionId = host.state.activeSessionId.get()
  publish()
  let minted
  try {
    minted = await ctx.rest('/session', { method: 'POST', body: {} })
  } catch (error) {
    tearDown(error && error.message ? error.message : 'Could not start Grok Voice')
    return
  }
  call.player = call.player || createPlayer()
  const ws = new WebSocket(minted.url, [`${minted.protocol_prefix}${minted.client_secret.value}`])
  call.ws = ws
  ws.onmessage = receive
  ws.onopen = async () => {
    send({ type: 'session.update', session: minted.session })
    call.state = 'live'
    publish()
    try {
      call.stopMic = await startMic(frame => send({ type: 'input_audio_buffer.append', audio: toBase64(frame) }))
    } catch (error) {
      tearDown('Microphone unavailable: ' + (error && error.message ? error.message : String(error)))
    }
  }
  ws.onclose = () => { if (call.ws === ws) tearDown(call.detail || 'The voice call ended') }
}

function VoiceButton ({ ctx }) {
  const [, rerender] = useState(0)
  const [status, setStatus] = useState(null)
  useEffect(() => {
    const fn = () => rerender(n => n + 1)
    call.listeners.add(fn)
    return () => call.listeners.delete(fn)
  }, [])
  useEffect(() => {
    ctx.rest('/status').then(setStatus, () => setStatus({ available: false, message: 'hermes-xai backend unavailable' }))
  }, [ctx])
  const live = call.state !== 'idle'
  const blocked = !live && status && !status.available
  const label = call.state === 'connecting' ? 'Connecting to Grok Voice'
    : live ? (call.delegations ? 'Grok Voice — Hermes is working (click to hang up)' : 'Grok Voice — listening (click to hang up)')
      : (blocked ? status.message : call.detail || `Talk with Grok Voice (${status ? status.model : 'grok-voice'})`)
  return h('button', {
    type: 'button',
    title: label,
    'aria-label': label,
    'aria-pressed': live,
    disabled: !!blocked,
    onClick: () => (live ? tearDown('') : void start(ctx)),
    className: 'inline-flex size-7 shrink-0 items-center justify-center rounded-full transition-colors ' +
      'hover:bg-muted disabled:opacity-50 ' + (live ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:text-foreground')
  }, h(live ? icons.VolumeX : icons.AudioLines, { className: icons.iconSize.sm }))
}

export default {
  id: 'hermes-xai',
  name: 'Grok Voice',
  defaultEnabled: true,
  register (ctx) {
    // The delegated turn's final text is what the voice says back.
    ctx.onEvent('message.complete', event => {
      if (!call.ws || !call.delegations || event.session_id !== call.sessionId) return
      call.delegations -= 1
      const text = String((event.payload && event.payload.text) || '').trim()
      call.results.push(text ? text.slice(0, 3000) : 'Hermes finished without a spoken result.')
      flushResults()
      publish()
    })
    ctx.onDispose(() => { tearDown(); call.player?.close(); call.player = null })
    ctx.register({ id: 'talk', area: 'composer.actions', order: 41, render: () => h(VoiceButton, { ctx }) })
  }
}

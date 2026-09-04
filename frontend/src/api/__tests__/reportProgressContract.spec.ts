import { describe, expect, it, vi } from 'vitest'
import {
  REPORT_PROGRESS_PROTOCOL_VERSION,
  createReportSseParser,
  parseReportProgressFrame,
  type ReportProgressFrame,
} from '@/api'

function validReadyFrame(): ReportProgressFrame {
  return {
    protocol_version: REPORT_PROGRESS_PROTOCOL_VERSION,
    task_id: 'task-d05',
    report_id: 'report-d05',
    sequence: 1,
    emitted_at: '2026-09-04T12:00:00Z',
    type: 'stream_ready',
    status: 'running',
    progress: 20,
    stages: [],
  }
}

function validStageFrame(sequence = 2): ReportProgressFrame {
  return {
    protocol_version: REPORT_PROGRESS_PROTOCOL_VERSION,
    task_id: 'task-d05',
    report_id: 'report-d05',
    sequence,
    emitted_at: '2026-09-04T12:00:10Z',
    type: 'stage_update',
    stage: 'FUNDAMENTAL_ANALYSIS',
    stage_status: 'SUCCEEDED',
    progress: 35,
  }
}

function validTerminalFrame(): ReportProgressFrame {
  return {
    protocol_version: REPORT_PROGRESS_PROTOCOL_VERSION,
    task_id: 'task-d05',
    report_id: 'report-d05',
    sequence: 3,
    emitted_at: '2026-09-04T12:01:00Z',
    type: 'task_terminal',
    status: 'completed',
    progress: 100,
    error_code: null,
    message: null,
  }
}

describe('report-progress-v1 public contract', () => {
  it('parses only the three strict typed frames', () => {
    const frames = [validReadyFrame(), validStageFrame(), validTerminalFrame()]
    expect(frames.map((frame) => parseReportProgressFrame(JSON.stringify(frame))))
      .toEqual(frames)
  })

  it('rejects malformed, unknown and sensitive frames', () => {
    expect(parseReportProgressFrame(JSON.stringify({ ...validStageFrame(), sequence: 0 })))
      .toBeNull()
    expect(parseReportProgressFrame(JSON.stringify({ ...validStageFrame(), progress: 101 })))
      .toBeNull()
    expect(parseReportProgressFrame(JSON.stringify({ ...validStageFrame(), stage: 'MADE_UP' })))
      .toBeNull()
    expect(parseReportProgressFrame(JSON.stringify({
      ...validStageFrame(),
      type: 'raw_langgraph_event',
    }))).toBeNull()
    expect(parseReportProgressFrame(JSON.stringify({
      ...validStageFrame(),
      authorization: 'Bearer MUST_NOT_LEAK',
      report_content: '# MUST_NOT_LEAK',
    }))).toBeNull()
    expect(parseReportProgressFrame('not-json')).toBeNull()
  })

  it('decodes comments, CRLF, multiline data, EOF and arbitrary chunks', () => {
    const received: ReportProgressFrame[] = []
    const invalid = vi.fn()
    const parser = createReportSseParser((frame) => received.push(frame), invalid)
    const prettyJson = JSON.stringify(validStageFrame(), null, 2)
    const event = [
      ': heartbeat',
      'event: stage_update',
      'id: 2',
      ...prettyJson.split('\n').map((line) => `data: ${line}`),
    ].join('\r\n')

    parser.push(event.slice(0, 19))
    parser.push(event.slice(19, 71))
    parser.push(event.slice(71))
    parser.finish()

    expect(received).toEqual([validStageFrame()])
    expect(invalid).not.toHaveBeenCalled()
  })

  it('reports a malformed business event without treating comments as failures', () => {
    const received = vi.fn()
    const invalid = vi.fn()
    const parser = createReportSseParser(received, invalid)

    parser.push(': heartbeat\n\ndata: {bad-json}\n\n')
    parser.finish()

    expect(received).not.toHaveBeenCalled()
    expect(invalid).toHaveBeenCalledTimes(1)
  })
})

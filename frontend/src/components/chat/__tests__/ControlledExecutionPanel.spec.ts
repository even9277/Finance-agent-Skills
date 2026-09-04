import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import type { ControlledExecutionState } from '@/stores/chatStore'

const execution: ControlledExecutionState = {
  requestId: 'request-d04',
  sessionId: 'session-d04',
  status: 'PARTIAL',
  activeRevision: 2,
  traces: [{
    stage: 'validate',
    status: 'SUCCEEDED',
    elapsed_ms: 1.5,
    summary: '执行计划已通过校验',
  }],
  planHistory: [
    { plan_id: 'plan-d04-1', revision: 1, validated: true },
    {
      plan_id: 'plan-d04-2',
      revision: 2,
      validated: true,
      replan_reason: '补充缺失的财务证据',
    },
  ],
  steps: [
    {
      plan_id: 'plan-d04-1',
      revision: 1,
      step_id: 'market-step',
      title: '获取行情数据',
      purpose: '补充行情证据',
      required: true,
      status: 'SUCCEEDED',
      depends_on: [],
      subject_summary: '贵州茅台（600519.SH）',
    },
    {
      plan_id: 'plan-d04-1',
      revision: 1,
      step_id: 'financial-step',
      title: '获取财务指标',
      purpose: '补充财务证据',
      required: true,
      status: 'REPLANNED',
      depends_on: [],
      subject_summary: '贵州茅台（600519.SH）',
    },
    {
      plan_id: 'plan-d04-2',
      revision: 2,
      step_id: 'replacement-step',
      title: '补充财务指标',
      purpose: '修复证据缺口',
      required: true,
      status: 'FAILED',
      depends_on: [],
      subject_summary: '贵州茅台（600519.SH）',
      error_code: 'TOOL_EXECUTION_FAILED',
    },
  ],
  tools: [{
    plan_id: 'plan-d04-2',
    revision: 2,
    tool_call_id: 'call-d04',
    step_id: 'replacement-step',
    display_name: '财务指标工具',
    status: 'FAILED',
    attempt: 1,
    elapsed_ms: 12.5,
    parameter_summary: ['标的：600519.SH'],
    result_summary: '调用失败',
    error_code: 'TOOL_EXECUTION_FAILED',
  }],
  verification: {
    plan_id: 'plan-d04-2',
    revision: 2,
    sufficiency: 'PARTIAL',
    claim_level: 'DESCRIPTIVE',
    accepted_count: 1,
    rejected_count: 1,
    covered_dimensions: ['market_snapshot'],
    missing_dimensions: ['financial_indicator'],
    limitation: '部分关键证据缺失，结论仅作描述性参考。',
  },
}

describe('ControlledExecutionPanel', () => {
  it('renders validated plan history, authoritative statuses and evidence limits', async () => {
    const { default: ControlledExecutionPanel } = await import(
      '@/components/chat/ControlledExecutionPanel.vue'
    )
    const wrapper = mount(ControlledExecutionPanel, {
      props: { execution },
    })

    expect(wrapper.text()).toContain('已校验计划')
    expect(wrapper.text()).toContain('第 2 版')
    expect(wrapper.text()).toContain('补充缺失的财务证据')
    expect(wrapper.text()).toContain('获取行情数据')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('财务指标工具')
    expect(wrapper.text()).toContain('调用失败')
    expect(wrapper.text()).toContain('证据部分充分')
    expect(wrapper.text()).toContain('financial_indicator')
    expect(wrapper.text()).toContain('部分关键证据缺失')
    expect(wrapper.text()).not.toContain('PRIVATE_')
  })

  it('renders nothing when the current request has no controlled state', async () => {
    const { default: ControlledExecutionPanel } = await import(
      '@/components/chat/ControlledExecutionPanel.vue'
    )
    const wrapper = mount(ControlledExecutionPanel, {
      props: { execution: null },
    })

    expect(wrapper.html()).toBe('<!--v-if-->')

    await wrapper.setProps({
      execution: {
        requestId: 'request-static',
        sessionId: 'session-static',
        status: 'NEEDS_CLARIFICATION',
        activeRevision: 0,
        traces: [],
        planHistory: [],
        steps: [],
        tools: [],
        verification: null,
      },
    })
    expect(wrapper.html()).toBe('<!--v-if-->')
  })
})

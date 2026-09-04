import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ReportProgress from '@/components/report/ReportProgress.vue'

describe('ReportProgress authoritative stage rendering', () => {
  it('renders backend stage states and an explicit polling fallback instead of thresholds', () => {
    const wrapper = mount(ReportProgress, {
      props: {
        progress: 50,
        status: 'running',
        transportStatus: 'FALLBACK_POLLING',
        stages: [
          { stage: 'PREPARING', status: 'SUCCEEDED' },
          { stage: 'FUNDAMENTAL_ANALYSIS', status: 'SUCCEEDED' },
          { stage: 'TECHNICAL_ANALYSIS', status: 'RUNNING' },
          { stage: 'VALUATION_ANALYSIS', status: 'SKIPPED' },
          { stage: 'NEWS_ANALYSIS', status: 'RUNNING' },
          { stage: 'SYNTHESIZING', status: 'RUNNING' },
        ],
      },
    })

    expect(wrapper.text()).toContain('已降级为轮询')
    expect(wrapper.text()).toContain('基本面')
    expect(wrapper.text()).toContain('技术面')
    expect(wrapper.text()).toContain('已跳过')
    expect(wrapper.text()).toContain('汇总生成')
    expect(wrapper.text()).toContain('50%')
  })
})

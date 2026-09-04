import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatInput from '@/components/chat/ChatInput.vue'

describe('ChatInput controlled stop action', () => {
  it('shows a visible stop action only while streaming and emits stop', async () => {
    const wrapper = mount(ChatInput, {
      props: { disabled: true, streaming: true },
    })

    const stop = wrapper.get('button[aria-label="停止生成"]')
    expect(stop.text()).toContain('停止生成')
    await stop.trigger('click')
    expect(wrapper.emitted('stop')).toHaveLength(1)

    await wrapper.setProps({ streaming: false })
    expect(wrapper.find('button[aria-label="停止生成"]').exists()).toBe(false)
  })
})

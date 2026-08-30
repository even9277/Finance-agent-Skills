import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SkillConfirmationCard from '@/components/chat/SkillConfirmationCard.vue'

describe('SkillConfirmationCard', () => {
  it('emits the selected Skill and supports local cancel', async () => {
    const wrapper = mount(SkillConfirmationCard, {
      props: {
        confirmation: {
          reason: '请选择分析方式',
          registry_snapshot_hash: 'a'.repeat(64),
          candidates: [
            {
              skill_name: 'fund-compare',
              confidence: 0.72,
              version: '1.1.0',
              reason: '匹配基金比较',
            },
          ],
        },
      },
    })

    expect(wrapper.text()).toContain('请选择分析方式')
    expect(wrapper.text()).toContain('fund-compare')
    await wrapper.get('[data-testid="confirm-fund-compare"]').trigger('click')
    expect(wrapper.emitted('confirm')?.[0]).toEqual(['fund-compare'])

    await wrapper.get('[data-testid="cancel-skill-confirmation"]').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })
})

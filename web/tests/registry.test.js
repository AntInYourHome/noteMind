import { describe, expect, it } from 'vitest'
import { registry } from '../src/modules/registry'

describe('前端工具注册表', () => {
  it('包含全部内置工具，key 与后端模块目录名一致', () => {
    expect(Object.keys(registry)).toEqual(
      expect.arrayContaining(['notes', 'log_parser', 'arm_registers'])
    )
  })

  it('每个注册项是懒加载函数', () => {
    for (const loader of Object.values(registry)) {
      expect(typeof loader).toBe('function')
    }
  })
})

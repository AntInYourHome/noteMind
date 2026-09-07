import { beforeEach, describe, expect, it } from 'vitest'
import { setUser, store, logout } from '../src/store'

describe('登录态 store', () => {
  beforeEach(() => localStorage.clear())

  it('setUser 持久化到 localStorage', () => {
    setUser({ id: 1, username: 'u1', is_admin: false })
    expect(store.user.username).toBe('u1')
    expect(JSON.parse(localStorage.getItem('user')).username).toBe('u1')
  })

  it('logout 清空登录态', () => {
    localStorage.setItem('token', 't')
    setUser({ id: 1, username: 'u1', is_admin: false })
    logout()
    expect(store.user).toBeNull()
    expect(localStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
  })
})

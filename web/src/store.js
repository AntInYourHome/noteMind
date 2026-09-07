import { reactive } from 'vue'

export const store = reactive({
  user: JSON.parse(localStorage.getItem('user') || 'null'),
})

export function setUser(user) {
  store.user = user
  localStorage.setItem('user', JSON.stringify(user))
}

export function logout() {
  store.user = null
  localStorage.removeItem('token')
  localStorage.removeItem('user')
}

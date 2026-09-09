import { reactive } from 'vue'

const defaults = { url: '', key: '' }

export const config = reactive({
  ...defaults,
  ...JSON.parse(localStorage.getItem('ig_config') || '{}')
})

export function saveConfig(patch) {
  Object.assign(config, patch)
  localStorage.setItem('ig_config', JSON.stringify({ url: config.url, key: config.key }))
}

export function serverBase() {
  if (import.meta.env.DEV) return ''
  return (config.url || '').replace(/\/+$/, '')
}

export class Unauthorized extends Error {}

export async function api(path, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== '' && v !== null && v !== undefined)
  ).toString()
  const resp = await fetch(`${serverBase()}${path}${qs ? `?${qs}` : ''}`, {
    headers: config.key ? { 'X-App-Key': config.key } : {}
  })
  if (resp.status === 401) throw new Unauthorized('app key 不正确')
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

export async function apiSend(path, method, body) {
  const resp = await fetch(`${serverBase()}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(config.key ? { 'X-App-Key': config.key } : {})
    },
    body: JSON.stringify(body)
  })
  if (resp.status === 401) throw new Unauthorized('app key 不正确')
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)
  return data
}

export function openExternal(url) {
  const cap = window.Capacitor
  if (cap?.Plugins?.Browser) {
    cap.Plugins.Browser.open({ url, presentationStyle: 'popover' })
  } else {
    window.open(url, '_blank', 'noopener')
  }
}

export function timeAgo(iso) {
  if (!iso) return ''
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

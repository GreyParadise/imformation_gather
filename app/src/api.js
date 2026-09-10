import { reactive } from 'vue'

const defaults = { url: '', key: '' }

export const ui = reactive({ needKey: false })

export const config = reactive({
  ...defaults,
  ...JSON.parse(localStorage.getItem('ig_config') || '{}')
})

export function saveConfig(patch) {
  let url = (patch.url ?? config.url ?? '').trim()
  if (url && !/^https?:\/\//i.test(url)) url = 'https://' + url
  const next = { ...config, ...patch, url }
  config.url = next.url
  config.key = next.key.trim()
  localStorage.setItem('ig_config', JSON.stringify({ url: config.url, key: config.key }))
}

export function serverBase() {
  if (import.meta.env.DEV) return ''
  const u = (config.url || '').replace(/\/+$/, '')
  if (!u) throw new Error('未填写 API 地址：请在下方填入完整隧道域名（https://xxx.trycloudflare.com）')
  return u
}

async function parseJson(resp) {
  const ct = resp.headers.get('content-type') || ''
  if (!ct.includes('json')) {
    throw new Error('服务器返回的不是 JSON——请检查 API 地址是否为后端隧道域名（不要带 /api 等路径后缀）')
  }
  return resp.json()
}

export class Unauthorized extends Error {}

export async function api(path, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== '' && v !== null && v !== undefined)
  ).toString()
  const resp = await fetch(`${serverBase()}${path}${qs ? `?${qs}` : ''}`, {
    headers: config.key ? { 'X-App-Key': config.key } : {}
  })
  if (resp.status === 401) { ui.needKey = true; throw new Unauthorized('app key 不正确') }
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return parseJson(resp)
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
  if (resp.status === 401) { ui.needKey = true; throw new Unauthorized('app key 不正确') }
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${resp.status}`)
  }
  return parseJson(resp)
}

export function mediaUrl(item) {
  if (!item.cover || !item.cover_token) return ''
  return `${serverBase()}/api/cover/${item.id}?t=${encodeURIComponent(item.cover_token)}`
}

export function rewriteReaderHtml(html) {
  return (html || '').replaceAll('src="/api/', `src="${serverBase()}/api/`)
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

export function withHttpScheme(value) {
  if (value.includes('://')) return value
  const host = /^[0-9a-f:]+$/i.test(value) && value.includes(':') ? '[' + value + ']' : value
  return 'http://' + host
}

export function applicationOrigin(input, port) {
  const value = withHttpScheme(input.trim())
  if (!/^https?:\/\/[^/]/i.test(value) || /[\\\s]/.test(value)) throw new Error('Invalid address')
  const url = new URL(value)
  if (!url.hostname || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Invalid address')
  }
  url.port = port
  return url.origin
}

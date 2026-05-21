export const config = { matcher: '/(.*)', }

const PASSWORD = process.env.AUTH_PASSWORD

export default function middleware(request) {
  if (!PASSWORD) return // dev: no password set, allow all

  const auth = request.headers.get('authorization') ?? ''
  if (auth.startsWith('Basic ')) {
    try {
      const decoded = atob(auth.slice(6))
      const pwd = decoded.slice(decoded.indexOf(':') + 1)
      if (pwd === PASSWORD) return // correct — pass through
    } catch {}
  }

  return new Response('Access denied', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Kitchen"',
      'Content-Type': 'text/plain',
    },
  })
}

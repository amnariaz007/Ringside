export function money(amount: string | number, currency = 'USD'): string {
  const n = typeof amount === 'string' ? Number(amount) : amount
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(n)
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function relative(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

/** "MERCHANDISE_OR_SERVICE_NOT_RECEIVED" -> "Merchandise or service not received" */
export function humanize(code: string): string {
  const s = code.replace(/_/g, ' ').toLowerCase()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export function hoursLeft(h: number | null): string {
  if (h === null) return 'no deadline'
  if (h < 0) return 'overdue'
  if (h < 48) return `${Math.floor(h)} h left`
  return `${Math.floor(h / 24)} days left`
}

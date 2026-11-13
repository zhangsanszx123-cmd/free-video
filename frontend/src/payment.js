/** ZPAY checkout helpers. Prices and signatures always come from the server. */
const LAST_ORDER_KEY = 'fv-last-order'

export const ORDER_STATUS = {
  pending: '待支付',
  paid: '已支付',
  refund_required: '待退款',
  refunded: '已退款',
}

export function orderStatusLabel(order) {
  return order.status === 'pending' && order.expired ? '未支付（已超时）' : ORDER_STATUS[order.status] || order.status
}

/** What buying `code` means for the current membership summary (mirrors backend payments.outcome). */
export function purchaseKind(summary, code) {
  const current = summary?.expires_at && new Date(summary.expires_at) > new Date() ? summary.plan : 'free'
  if (current === 'free') return 'new'
  if (current === code) return 'renew'
  return current === 'monthly' && code === 'yearly' ? 'upgrade' : 'refused'
}

export function rememberOrder(no) {
  try { sessionStorage.setItem(LAST_ORDER_KEY, no) } catch { /* optional */ }
}

export function lastOrder() {
  try { return sessionStorage.getItem(LAST_ORDER_KEY) || '' } catch { return '' }
}

/** Page-jump payment: POST the signed fields to the ZPAY cashier (submit.php). */
export function submitToGateway(action, fields) {
  const form = document.createElement('form')
  form.method = 'POST'
  form.action = action
  form.acceptCharset = 'UTF-8'
  form.style.display = 'none'
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement('input')
    input.type = 'hidden'
    input.name = name
    input.value = value
    form.appendChild(input)
  }
  document.body.appendChild(form)
  form.submit()
  form.remove()
}

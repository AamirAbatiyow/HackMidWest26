/** `/` is the splash; the live payables queue lives at `/app` so a deep link can skip the splash. */
export const SPLASH_PATH = '/'
export const QUEUE_PATH = '/app'

export function queueUrl(paymentId?: string | null): string {
  return paymentId ? `${QUEUE_PATH}?payment=${encodeURIComponent(paymentId)}` : QUEUE_PATH
}

/**
 * 统一时间格式化工具
 *
 * 后端统一输出 UTC ISO 字符串 (如 "2026-07-22T16:03:21+00:00" 或 "2026-07-22T16:03:21Z")
 * 前端统一转为浏览器本地时区显示
 */

/**
 * 将 ISO 时间字符串转为本地时间 HH:MM:SS
 * @param isoString - UTC ISO 时间字符串
 * @returns 本地时间格式 HH:MM:SS, 或 "--:--:--" 如果输入为空
 */
export function formatTime(isoString: string | undefined | null): string {
  if (!isoString) return '--:--:--'
  try {
    const date = new Date(isoString)
    if (isNaN(date.getTime())) return '--:--:--'
    return date.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return '--:--:--'
  }
}

/**
 * 将 ISO 时间字符串转为本地日期时间 YYYY-MM-DD HH:MM:SS
 * @param isoString - UTC ISO 时间字符串
 * @returns 本地日期时间格式, 或 "--" 如果输入为空
 */
export function formatDateTime(isoString: string | undefined | null): string {
  if (!isoString) return '--'
  try {
    const date = new Date(isoString)
    if (isNaN(date.getTime())) return '--'
    // 格式化为 YYYY-MM-DD HH:MM:SS
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    const seconds = String(date.getSeconds()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
  } catch {
    return '--'
  }
}

/**
 * 将 ISO 时间字符串转为简短本地日期时间 MM-DD HH:MM
 * @param isoString - UTC ISO 时间字符串
 * @returns 简短本地日期时间格式, 或 "--" 如果输入为空
 */
export function formatShortDateTime(isoString: string | undefined | null): string {
  if (!isoString) return '--'
  try {
    const date = new Date(isoString)
    if (isNaN(date.getTime())) return '--'
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    return `${month}-${day} ${hours}:${minutes}`
  } catch {
    return '--'
  }
}

/**
 * 将 Unix 时间戳(秒)转为本地日期时间 YYYY-MM-DD HH:MM:SS
 * @param unixSeconds - Unix 时间戳 (秒)
 * @returns 本地日期时间格式
 */
export function formatUnixTimestamp(unixSeconds: number | string | undefined | null): string {
  if (!unixSeconds) return '--'
  try {
    const ts = typeof unixSeconds === 'string' ? parseInt(unixSeconds, 10) : unixSeconds
    if (isNaN(ts) || ts <= 0) return '--'
    const date = new Date(ts * 1000)
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return '--'
  }
}

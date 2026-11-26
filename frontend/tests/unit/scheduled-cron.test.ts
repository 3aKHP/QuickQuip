import { describe, expect, it } from 'vitest'
import {
  assembleCron,
  describeSchedule,
  localInputToRunAt,
  parseCronToSimple,
  runAtToLocalInput,
} from '@/lib/scheduledCron'

describe('scheduledCron cross-year one-off support', () => {
  it('converts between local datetime input and Beijing ISO run_at', () => {
    expect(localInputToRunAt('2027-01-15T09:30')).toBe('2027-01-15T09:30:00+08:00')
    expect(runAtToLocalInput('2027-01-15T09:30:00+08:00')).toBe('2027-01-15T09:30')
    expect(localInputToRunAt('')).toBe('')
  })

  it('preserves exact cross-year run_at when parsing back to simple mode', () => {
    const parsed = parseCronToSimple('30 9 15 1 *', false, '2027-01-15T09:30:00+08:00')
    expect(parsed).not.toBeNull()
    expect(parsed?.frequency).toBe('once')
    expect(parsed?.onceAt).toBe('2027-01-15T09:30')
    expect(assembleCron(parsed!)).toBe('30 9 15 1 *')
    expect(describeSchedule('30 9 15 1 *', false, '2027-01-15T09:30:00+08:00')).toBe('单次 2027-01-15 09:30')
  })

  it('describes standard recurring schedules in plain Chinese', () => {
    expect(describeSchedule('0 8 * * *', true)).toBe('每天 08:00')
    expect(describeSchedule('15 21 * * 4', true)).toBe('每周五 21:15')
    expect(describeSchedule('5 9 1 * *', true)).toBe('每月 1 号 09:05')
  })
})

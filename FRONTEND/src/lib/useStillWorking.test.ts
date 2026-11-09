import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { STILL_WORKING_AFTER_MS, useStillWorking } from './useStillWorking';

describe('useStillWorking', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('reassures the reader only once a load has taken a while', () => {
    const say = vi.fn();
    renderHook(() => useStillWorking(true, say));
    vi.advanceTimersByTime(STILL_WORKING_AFTER_MS - 1);
    expect(say).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(say).toHaveBeenCalledWith('think', expect.stringMatching(/still working/i));
  });

  it('says nothing if the load finishes first, or nothing is loading', () => {
    const say = vi.fn();
    const { rerender } = renderHook(({ loading }) => useStillWorking(loading, say), { initialProps: { loading: true } });
    rerender({ loading: false });
    vi.advanceTimersByTime(STILL_WORKING_AFTER_MS * 2);
    expect(say).not.toHaveBeenCalled();
  });
});

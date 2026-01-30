import React, { useEffect, useState } from 'react';

interface TimerBarProps {
  duration: number; // in milliseconds
  onComplete?: () => void;
  onMarkerReached?: (markerId: number) => void;
  markers?: number[]; // percentages (0-100) where events should trigger
  isRunning?: boolean;
  adjustment?: { id: number; amountMs: number }; // Signal to adjust time
  timeRemaining?: number; // Authoritative time remaining in MS
}

export const TimerBar: React.FC<TimerBarProps> = ({
  duration,
  onComplete,
  onMarkerReached,
  markers = [],
  isRunning = true,
  adjustment,
  timeRemaining
}) => {
  const [progress, setProgress] = useState(100);

  // We need to track the "virtual" start time to allow adding/removing time
  // If we mistakenly just change progress, the interval will overwrite it based on Date.now()
  // So we track an offset.
  const offsetRef = React.useRef(0);
  const adjustmentIdRef = React.useRef<number | undefined>(undefined);
  // Track last synced time to avoid loops if needed, though simple diff is fine
  const lastTimeRemainingRef = React.useRef<number | undefined>(undefined);

  useEffect(() => {
    if (adjustment && adjustment.id !== adjustmentIdRef.current) {
      offsetRef.current += adjustment.amountMs;
      adjustmentIdRef.current = adjustment.id;
    }
  }, [adjustment]);

  // Sync with authoritative time
  useEffect(() => {
    if (timeRemaining !== undefined && timeRemaining !== lastTimeRemainingRef.current) {
      // Calculate what the elapsed SHOULD be
      const impliedElapsed = duration - timeRemaining;
      // Our loop uses: realElapsed - offset = effectiveElapsed
      // So: realElapsed - offset = impliedElapsed
      // offset = realElapsed - impliedElapsed
      // We need 'startTime' to know realElapsed.
      // But startTime is local to the effect below.
      // We can't access it here easily unless we ref it.
      // Alternative: Just set a "syncNeeded" flag or value ref that the loop consumes?
      // Or simpler: The loop uses Date.now(). We can reset startTime or offset in the loop.

      // Let's store the target effective elapsed in a ref
      syncTargetRef.current = impliedElapsed;
      lastTimeRemainingRef.current = timeRemaining;
    }
  }, [timeRemaining, duration]);

  const syncTargetRef = React.useRef<number | undefined>(undefined);

  // Store callbacks in refs to avoid re-running effect when they change
  const onMarkerReachedRef = React.useRef(onMarkerReached);
  const onCompleteRef = React.useRef(onComplete);

  useEffect(() => {
    onMarkerReachedRef.current = onMarkerReached;
    onCompleteRef.current = onComplete;
  }, [onMarkerReached, onComplete]);

  // Track triggered markers to prevent duplicates
  const [triggeredMarkers, setTriggeredMarkers] = useState<Set<number>>(new Set());
  const prevProgressRef = React.useRef(100);

  useEffect(() => {
    // Reset when duration changes or we restart
    setTriggeredMarkers(new Set());
    prevProgressRef.current = 100;
    offsetRef.current = 0;
    setProgress(100);
    syncTargetRef.current = undefined;
    setProgress(100);
    syncTargetRef.current = undefined;
  }, [duration, JSON.stringify(markers)]);

  useEffect(() => {
    if (!isRunning) return;

    const startTime = Date.now();
    const interval = 16; // ~60fps

    const timer = setInterval(() => {
      // Calculate elapsed based on real time MINUS the offset (negative offset = added time, positive = removed time)
      // Actually: remaining = duration - (realElapsed - addedTime)
      // offsetRef stores "added time" (positive) or "removed time" (negative)
      // improved: let offset be "total adjusted ms". Positive = add time (increase remaining).

      const realElapsed = Date.now() - startTime;

      // Sync if needed
      if (syncTargetRef.current !== undefined) {
        // calculated offset so that: realElapsed - offset = syncTarget
        offsetRef.current = realElapsed - syncTargetRef.current;
        syncTargetRef.current = undefined; // Consume it
      }

      // Cap the offset to ensure we don't have "negative" elapsed time (meaning > 100% time left)
      if (realElapsed - offsetRef.current < 0) {
        offsetRef.current = realElapsed;
      }

      const effectiveElapsed = realElapsed - offsetRef.current;
      const remaining = Math.max(0, duration - effectiveElapsed);

      // Allow remaining to exceed duration? No, cap at duration usually.
      // But for visual bar, 100% is max.
      const clampedRemaining = Math.min(duration, remaining);
      const newProgress = (clampedRemaining / duration) * 100;

      // Check for crossed markers
      // We are going DOWN from 100 to 0.
      markers.forEach((marker) => {
        if (prevProgressRef.current > marker && newProgress <= marker) {
          onMarkerReachedRef.current?.(marker);
        }
      });

      prevProgressRef.current = newProgress;
      setProgress(newProgress);

      if (remaining <= 0) {
        clearInterval(timer);
        onCompleteRef.current?.();
      }
    }, interval);

    return () => clearInterval(timer);
    return () => clearInterval(timer);
  }, [duration, isRunning, JSON.stringify(markers)]); // Serialize markers to avoid ref change issues

  return (
    <div className="w-full h-3 bg-white/10 rounded-full overflow-hidden relative mt-4">
      <div
        className="h-full bg-purple-500 transition-all ease-linear"
        style={{ width: `${progress}%` }}
      />
      {markers.map((m, i) => (
        <div
          key={i}
          className="absolute top-0 bottom-0 w-0.5 bg-white/50"
          style={{ left: `${m}%` }}
        />
      ))}
    </div>
  );
};

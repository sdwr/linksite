import React, { useEffect, useState } from 'react';

interface TimerBarProps {
  duration: number; // in milliseconds
  onComplete?: () => void;
  onMarkerReached?: (markerId: number) => void;
  markers?: number[]; // percentages (0-100) where events should trigger
  isRunning?: boolean;
  adjustment?: { id: number; amountMs: number }; // Signal to adjust time
}

export const TimerBar: React.FC<TimerBarProps> = ({
  duration,
  onComplete,
  onMarkerReached,
  markers = [],
  isRunning = true,
  adjustment
}) => {
  const [progress, setProgress] = useState(100);

  // We need to track the "virtual" start time to allow adding/removing time
  // If we mistakenly just change progress, the interval will overwrite it based on Date.now()
  // So we track an offset.
  const offsetRef = React.useRef(0);
  const adjustmentIdRef = React.useRef<number | undefined>(undefined);

  useEffect(() => {
    if (adjustment && adjustment.id !== adjustmentIdRef.current) {
      offsetRef.current += adjustment.amountMs;
      adjustmentIdRef.current = adjustment.id;
    }
  }, [adjustment]);

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
  }, [duration, markers]);

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

      // Cap the offset to ensure we don't have "negative" elapsed time (meaning > 100% time left)
      // effectiveElapsed = real - offset.
      // If effectiveElapsed < 0, it means we have > 100% remaining.
      // We want effectiveElapsed >= 0.
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
  }, [duration, isRunning, markers]); // Removed callbacks from dependencies

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

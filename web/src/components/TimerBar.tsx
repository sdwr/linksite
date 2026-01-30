import React, { useEffect, useState } from 'react';

interface TimerBarProps {
  duration: number; // in milliseconds
  onComplete?: () => void;
  onMarkerReached?: (markerId: number) => void;
  markers?: number[]; // percentages (0-100) where events should trigger
  isRunning?: boolean;
}

export const TimerBar: React.FC<TimerBarProps> = ({
  duration,
  onComplete,
  onMarkerReached,
  markers = [],
  isRunning = true,
}) => {
  const [progress, setProgress] = useState(100);

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
    setProgress(100);
  }, [duration, markers]);

  useEffect(() => {
    if (!isRunning) return;

    const startTime = Date.now();
    const interval = 16; // ~60fps

    const timer = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const remaining = Math.max(0, duration - elapsed);
      const newProgress = (remaining / duration) * 100;

      // Check for crossed markers
      // We are going DOWN from 100 to 0.
      // A marker M is crossed if prev > M and curr <= M.
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
    <div className="w-full h-1 bg-white/10 rounded-full overflow-hidden relative mt-4">
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

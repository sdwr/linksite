import React from 'react';
import { SatelliteNode } from '@/types';

interface SatelliteListProps {
  connections: SatelliteNode[];
  revealedCount: number;
  onSelect: (targetId: string) => void;
  probabilities?: Record<string, number>; // id -> 0-1 probability
  transitionTargetId?: string | null;
  transitionPhase?: 'IDLE' | 'PRE' | 'RUNNING';
}

export const SatelliteList: React.FC<SatelliteListProps> = ({
  connections,
  revealedCount,
  onSelect,
  probabilities = {},
  transitionTargetId,
  transitionPhase = 'IDLE'
}) => {
  // Take only up to 5 connections
  const satellites = connections.slice(0, 5);
  const totalSatellites = satellites.length;
  // Calculate middle index for centering logic based on list height
  // List items are approx 80px + 24px gap = 104px.
  // Center of list is roughly (total - 1) / 2.


  return (
    <div className="absolute right-12 top-1/2 -translate-y-1/2 flex flex-col gap-6 z-40 w-80 pointer-events-none">
      {satellites.map((conn, index) => {
        const isRevealed = index < revealedCount;
        const probability = probabilities[conn.targetId] || 0;

        // Gradient color based on probability
        // Low prob: Blue -> High prob: Purple/Pink
        // Simplified for now: opacity/intensity

        // Show outline if not revealed
        // Show full content if revealed
        const isTarget = transitionTargetId === conn.targetId;
        const isOther = transitionTargetId && !isTarget;

        // Calculate vertical offset to center
        // If this item is at index i, and we want it to move to Center Screen Y.
        // Current Y relative to List Center is: (index - (total-1)/2) * 104px.
        // So we need to translate BY -(Current Y).
        const offsetIndex = index - (totalSatellites - 1) / 2;
        const flyY = offsetIndex * 104 * -1; // Invert to move to center

        return (
          <div
            key={conn.targetId}
            className={`
                pointer-events-auto
                transform transition-all duration-500 ease-out
                rounded-xl
                ${isTarget && transitionPhase === 'PRE' ? 'animate-pulse-glow z-50 scale-105 border-yellow-500 shadow-yellow-500/50' : ''}
                ${isTarget && transitionPhase === 'RUNNING' ? 'animate-fly-to-center !opacity-100 !z-50 border-yellow-500 shadow-yellow-500/50' : ''}
                ${isOther && transitionPhase !== 'IDLE' ? 'opacity-0 scale-90 blur-sm pointer-events-none transition-opacity duration-300' : ''}
                ${!transitionTargetId && (isRevealed ? 'translate-x-0 opacity-100 scale-100' : 'translate-x-4 opacity-40 scale-95')}
                active:scale-95 active:border-purple-500 transition-transform
              `}
            style={
              {
                transitionDelay: isTarget ? '0ms' : `${index * 100}ms`,
                '--fly-y': `${flyY}px`,
                animationDelay: isTarget && transitionPhase === 'RUNNING' ? '200ms' : '0ms'
              } as React.CSSProperties
            }
            onClick={(e) => {
              if (isRevealed && !transitionTargetId) {
                onSelect(conn.targetId);
                // Add quick pulse animation or splash
                const el = e.currentTarget;
                el.classList.add('scale-110', 'brightness-125');
                setTimeout(() => el.classList.remove('scale-110', 'brightness-125'), 200);
              }
            }}
          >
            <div
              className={`
                    relative p-4 rounded-xl border-2
                    ${isRevealed ? 'border-white/10 bg-black/90 backdrop-blur-xl hover:scale-105 hover:bg-neutral-900 cursor-pointer shadow-xl' : 'border-dashed border-white/20 bg-transparent cursor-default'}
                    group overflow-hidden transition-all duration-500 min-h-[80px] flex items-center
                `}
            >
              {/* Probability Glow Border Override - Only when revealed */}
              <div
                className={`absolute inset-0 pointer-events-none transition-opacity duration-700 ${isRevealed && probability > 0.3 ? 'opacity-100' : 'opacity-0'} group-hover:opacity-100`}
              >
                <div className={`absolute inset-0 bg-gradient-to-r ${isRevealed && probability > 0.3 ? 'from-purple-500/20 via-blue-500/20 to-purple-500/20 animate-gradient-x' : 'from-transparent via-blue-500/10 to-transparent'}`} />
              </div>

              <div className={`flex items-center justify-between gap-4 relative z-10 w-full transition-opacity duration-500 ${isRevealed ? 'opacity-100' : 'opacity-0'}`}>
                <div className="flex flex-col">
                  <span className={`text-xs font-mono tracking-wider uppercase mb-0.5 transition-colors ${isRevealed && probability > 0.3 ? 'text-purple-300' : 'text-neutral-500'}`}>
                    {conn.label}
                  </span>
                  <span className={`font-medium text-sm line-clamp-1 ${isRevealed ? 'text-white' : 'text-neutral-500'}`}>
                    {conn.title}
                  </span>
                </div>
                {/* Probability Indicator - invisible/dimmed if not revealed */}
                <div
                  className={`w-1.5 h-8 rounded-full bg-white/5 overflow-hidden transition-opacity ${isRevealed ? 'opacity-100' : 'opacity-20'}`}
                >
                  <div
                    className={`w-full rounded-full transition-all duration-1000 ${isRevealed && probability > 0.3 ? 'bg-gradient-to-t from-blue-500 via-purple-500 to-pink-500 animate-pulse' : 'bg-neutral-600'}`}
                    style={{ height: `${Math.max(15, probability * 100)}%`, marginTop: 'auto' }}
                  />
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

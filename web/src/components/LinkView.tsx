'use client';

import React, { useState, useMemo, useEffect } from 'react';
import { MessageSquare, Send } from 'lucide-react';
import { LinkCard } from './LinkCard';
import { TimerBar } from './TimerBar';
import { SatelliteList } from './SatelliteList';
import { useLinkSite } from '@/contexts/LinkSiteContext';
import { LinkSiteState } from '@/types';

const LinkViewComponent: React.FC = () => {
  const { state: providerState, react, nominate } = useLinkSite();

  // Buffered state to allow for transition animations while provider updates immediately
  const [viewState, setViewState] = useState<LinkSiteState>(providerState);

  // Animation States
  const [revealedCount, setRevealedCount] = useState(0);
  const [transitionTargetId, setTransitionTargetId] = useState<string | null>(null);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [transitionPhase, setTransitionPhase] = useState<'IDLE' | 'PRE' | 'RUNNING'>('IDLE');
  const [timeAdjustment, setTimeAdjustment] = useState<{ id: number, amountMs: number } | undefined>(undefined);

  const currentNode = viewState.featured.link;
  const DURATION = viewState.featured.totalDuration * 1000; // Seconds to MS
  const SATELLITE_COUNT = viewState.satellites.length;

  // Sync with Provider, handling Transitions
  useEffect(() => {
    // If the provider has rotated to a new link...
    if (providerState.featured.link.id !== viewState.featured.link.id) {
      // Identify which satellite is the new target (so we can glow it)
      // We look for the new ID in the *current* viewState's satellites
      const targetId = providerState.featured.link.id;
      const isSatellite = viewState.satellites.find(s => s.id === targetId);

      if (isSatellite) {
        handleTransitionSequence(targetId, providerState);
      } else {
        // Hard swap if not found (e.g. initial load mismatch or wildcard)
        setViewState(providerState);
        // Immediate reveal on hard swap
        setTimeout(() => setRevealedCount(providerState.satellites.length), 300);
      }
    } else {
      // Regular update (Timer tick, votes, comments) - sync immediately if not transitioning
      if (!isTransitioning) {
        setViewState(providerState);
      }
    }
  }, [providerState, viewState.featured.link.id, isTransitioning]);

  // Initial Reveal
  useEffect(() => {
    if (revealedCount === 0 && !isTransitioning) {
      setTimeout(() => setRevealedCount(SATELLITE_COUNT), 300);
    }
  }, []);

  const handleTransitionSequence = (targetId: string, nextState: LinkSiteState) => {
    if (isTransitioning) return;
    setIsTransitioning(true);
    setTransitionTargetId(targetId);
    setTransitionPhase('PRE');

    // 1. Pre-transition (Glow phase)
    setTimeout(() => {
      setTransitionPhase('RUNNING');

      // 2. Running Phase (Animation)
      setTimeout(() => {
        // Swap Data
        setViewState(nextState);
        setTransitionTargetId(null);
        setTransitionPhase('IDLE');
        setIsTransitioning(false);
        // Reset reveal for new state - Immediate Reveal!
        setRevealedCount(0); // Reset briefly
        setTimeout(() => setRevealedCount(nextState.satellites.length), 100);
      }, 1300);
    }, 800);
  };

  const handleAdjustTime = (amountMs: number) => {
    // Optimistic Update
    setTimeAdjustment({ id: Date.now(), amountMs });

    // amountMs > 0 is "Add Time" (Upvote/Like -> 1)
    // amountMs < 0 is "Remove Time" (Downvote/Dislike -> -1)
    // Backend expects 1 or -1
    const val = amountMs > 0 ? 1 : -1;
    react(currentNode.id, val);
  };

  // Background Lines Logic
  const getLineCoordinates = (index: number, total: number) => {
    const centerX = '50%';
    const centerY = '50%';
    const targetX = '82%';
    const offset = (index - (total - 1) / 2) * 12;
    const targetY = `${50 + offset}%`;
    return { x1: centerX, y1: centerY, x2: targetX, y2: targetY };
  };

  // Probability Calculation
  const totalNominations = viewState.satellites.reduce((acc, s) => acc + (s.nominations || 0), 0);
  const probabilities = viewState.satellites.reduce((acc, sat) => {
    if (totalNominations === 0) {
      acc[sat.id] = 1 / SATELLITE_COUNT;
    } else {
      acc[sat.id] = (sat.nominations || 0) / totalNominations;
    }
    return acc;
  }, {} as Record<string, number>);

  return (
    <div className="relative w-full h-screen bg-[#050505] text-white overflow-hidden selection:bg-purple-500/30 font-sans">

      {/* Background Ambient Glow */}
      <div className="absolute top-[-20%] left-[-20%] w-[50%] h-[50%] bg-purple-900/10 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-20%] w-[50%] h-[50%] bg-blue-900/10 blur-[120px] rounded-full pointer-events-none" />

      {/* Transition Wrapper */}
      <div className="absolute inset-0 w-full h-full">

        {/* SVG Tether Layer */}
        <svg className={`absolute inset-0 w-full h-full pointer-events-none z-10 transition-opacity duration-500 ${isTransitioning ? 'opacity-0' : 'opacity-100'}`}>
          {viewState.satellites.slice(0, 5).map((conn, index) => {
            const coords = getLineCoordinates(index, Math.min(SATELLITE_COUNT, 5));
            const isRevealed = index < revealedCount;
            return (
              <line
                key={conn.id} // SatelliteNode has id
                x1={coords.x1}
                y1={coords.y1}
                x2={coords.x2}
                y2={coords.y2}
                stroke="rgba(255,255,255,0.1)"
                strokeWidth={isRevealed ? "2" : "1"}
                strokeDasharray={isRevealed ? "none" : "5,5"}
                className={`transition-all duration-1000 ${isRevealed ? 'opacity-50' : 'opacity-20'}`}
              />
            );
          })}
        </svg>

        {/* Center Stage */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 flex flex-col items-center w-full max-w-4xl">
          <div
            key={currentNode.id}
            className={`w-full flex flex-col items-center transition-all duration-500 ${transitionPhase === 'RUNNING' ? 'animate-slide-out-left' : ''} ${!isTransitioning ? 'animate-fade-in' : ''}`}
          >
            <LinkCard node={currentNode} />

            {/* Timer Bar + Controls */}
            <div className={`w-[900px] max-w-[90vw] mt-6 flex items-center gap-4 transition-opacity duration-300 ${transitionPhase !== 'IDLE' ? 'opacity-50 blur-sm pointer-events-none' : ''}`}>
              {/* Reject / Subtract Time (-3s or -1 vote) */}
              <button
                onClick={() => handleAdjustTime(-3000)}
                className="p-3 rounded-full bg-neutral-900 border border-white/10 hover:border-red-500/50 hover:bg-neutral-800 text-neutral-400 hover:text-red-500 transition-all group"
              >
                <span className="font-bold text-xl group-active:scale-90 transition-transform block">✕</span>
              </button>

              <div className="flex-1">
                <TimerBar
                  key={currentNode.id}
                  duration={DURATION}
                  isRunning={!isTransitioning}
                  adjustment={timeAdjustment}
                  timeRemaining={viewState.featured.timeRemaining * 1000}
                  onComplete={() => {
                    // Do nothing. Provider handles rotation.
                  }}
                />
              </div>

              {/* Approve / Add Time (+10s or +1 vote) */}
              <button
                onClick={() => handleAdjustTime(10000)}
                className="p-3 rounded-full bg-neutral-900 border border-white/10 hover:border-green-500/50 hover:bg-neutral-800 text-neutral-400 hover:text-green-500 transition-all group"
              >
                <div className="font-bold text-xl group-active:scale-90 transition-transform block">✓</div>
              </button>
            </div>

            {/* Comments */}
            <div className={`w-[900px] max-w-[90vw] mt-6 bg-neutral-900/80 backdrop-blur-md rounded-xl p-6 border border-white/5 transition-all duration-300 ${transitionPhase !== 'IDLE' ? 'opacity-50 blur-sm pointer-events-none' : ''}`}>
              <div className="flex items-center gap-2 mb-4 text-neutral-400">
                <MessageSquare size={16} />
                <span className="text-sm font-medium uppercase tracking-wider">Discussion</span>
              </div>
              <div className="space-y-3 max-h-[150px] overflow-y-auto pr-2 custom-scrollbar">
                {currentNode.comments?.map((comment, idx) => (
                  <div key={idx} className="text-sm group">
                    <span className="font-bold text-purple-400 mr-2">{comment.user}</span>
                    <span className="text-neutral-300 group-hover:text-white transition-colors">{comment.text}</span>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex gap-2">
                <input
                  type="text"
                  placeholder="Add a comment..."
                  className="flex-1 bg-black/50 border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-purple-500/50 transition-colors"
                />
                <button className="p-2 bg-white text-black rounded-lg hover:bg-neutral-200 transition-colors">
                  <Send size={16} />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Satellites */}
        <SatelliteList
          connections={viewState.satellites}
          revealedCount={revealedCount}
          probabilities={probabilities}
          onSelect={(id) => nominate(id)}
          transitionTargetId={transitionTargetId}
          transitionPhase={transitionPhase}
        />
      </div>
    </div>
  );
};

export const LinkView = React.memo(LinkViewComponent);

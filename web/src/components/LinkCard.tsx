import React from 'react';
import { ExternalLink, Play, MessageCircle, ArrowBigUp } from 'lucide-react';
import { LinkNode } from '@/types';

interface LinkCardProps {
  node: LinkNode;
}

const getLinkType = (url: string): 'youtube' | 'reddit' | 'bluesky' | 'default' => {
  try {
    const u = new URL(url);
    if (u.hostname.includes('youtube.com') || u.hostname.includes('youtu.be')) return 'youtube';
    if (u.hostname.includes('reddit.com')) return 'reddit';
    if (u.hostname.includes('bsky.app')) return 'bluesky';
  } catch (e) {
    // console.warn('Invalid URL', url); 
  }
  return 'default';
};

const getYouTubeId = (url: string): string | null => {
  try {
    const u = new URL(url);
    if (u.hostname.includes('youtu.be')) return u.pathname.slice(1);
    return u.searchParams.get('v');
  } catch (e) {
    return null;
  }
};

export const LinkCard: React.FC<LinkCardProps> = ({ node }) => {
  const type = getLinkType(node.url);

  // --- YouTube Card ---
  if (type === 'youtube') {
    const videoId = getYouTubeId(node.url);
    const thumb = videoId ? `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg` : node.screenshot_url;

    return (
      <div className="relative group w-[900px] max-w-[90vw] bg-black rounded-2xl overflow-hidden shadow-2xl border border-red-500/20 hover:border-red-500/40 transition-all duration-500">
        <div className="relative aspect-video w-full overflow-hidden bg-black">
          {/* Thumbnail */}
          <img src={thumb} alt={node.title} className="w-full h-full object-cover opacity-80 group-hover:opacity-60 transition-opacity" />

          {/* Play Button Overlay */}
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-20 h-20 bg-red-600 rounded-full flex items-center justify-center shadow-[0_0_30px_rgba(220,38,38,0.5)] group-hover:scale-110 transition-transform">
              <Play fill="white" className="text-white ml-2" size={32} />
            </div>
          </div>

          {/* Text Overlay */}
          <div className="absolute bottom-0 left-0 right-0 p-6 bg-gradient-to-t from-black/90 to-transparent">
            <h1 className="text-2xl font-bold text-white line-clamp-2">{node.title}</h1>
            <div className="flex items-center gap-2 mt-2 text-sm text-neutral-400">
              <span className="bg-red-600/20 text-red-400 px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wider">YouTube</span>
              <span>{node.feed_name || 'Channel'}</span>
            </div>
          </div>
        </div>
        {/* Glow */}
        <div className="absolute -inset-1 bg-gradient-to-r from-red-600 to-orange-600 rounded-2xl blur-xl opacity-10 -z-10 group-hover:opacity-30 transition-opacity duration-500" />
      </div>
    );
  }

  // --- Reddit Card ---
  if (type === 'reddit') {
    return (
      <div className="relative group w-[900px] max-w-[90vw] bg-[#1A1A1B] rounded-2xl overflow-hidden shadow-2xl border border-white/10 hover:border-[#FF4500]/50 transition-all duration-500 p-8">
        <div className="flex gap-4">
          {/* Score Column */}
          <div className="flex flex-col items-center gap-1 text-neutral-400 bg-black/20 p-2 rounded-lg h-fit">
            <ArrowBigUp size={28} className="text-[#FF4500]" />
            <span className="font-bold text-sm">{node.stats?.upvotes || 0}</span>
          </div>

          {/* Content */}
          <div className="flex-1">
            <div className="flex items-center gap-2 text-xs text-neutral-400 mb-2">
              <span className="font-bold text-white text-sm">{node.feed_name || 'r/subreddit'}</span>
              <span>•</span>
              <span>Posted by {node.description || 'u/user'}</span>
            </div>

            <h1 className="text-2xl font-bold text-white mb-4 leading-snug">{node.title}</h1>

            {/* Render thumbnail if available and not just 'self' */}
            {node.screenshot_url && !node.screenshot_url.includes('default') && (
              <div className="w-full h-64 bg-black/50 rounded-xl overflow-hidden mb-4 border border-white/5">
                <img src={node.screenshot_url} alt="Post content" className="w-full h-full object-contain" />
              </div>
            )}

            <div className="flex items-center gap-4 text-neutral-400 text-sm font-bold bg-white/5 w-fit px-4 py-2 rounded-full">
              <MessageCircle size={18} />
              <span>{node.stats?.downvotes || '0'} Comments</span>
              {/* Note: using downvotes field for comments temporarily as mock stats are limited */}
            </div>
          </div>
        </div>
        {/* Glow */}
        <div className="absolute -inset-1 bg-gradient-to-r from-[#FF4500] to-orange-500 rounded-2xl blur-xl opacity-10 -z-10 group-hover:opacity-20 transition-opacity duration-500" />
      </div>
    );
  }

  // --- Bluesky / Social Card ---
  if (type === 'bluesky') {
    return (
      <div className="relative group w-[900px] max-w-[90vw] bg-[#001933] rounded-2xl overflow-hidden shadow-2xl border border-white/10 hover:border-[#0085ff]/50 transition-all duration-500 p-8">
        <div className="flex gap-4">
          {/* Avatar Placeholder */}
          <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex-shrink-0" />

          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-bold text-white text-lg">{node.feed_name || 'Bluesky User'}</span>
              <span className="text-blue-400 text-sm">@{node.feed_name?.toLowerCase().replace(/\s+/g, '') || 'handle.bsky.social'}</span>
            </div>

            <p className="text-white text-xl leading-relaxed mb-4">
              {node.description || node.title}
              {/* Bsky usually puts content in description or title depending on scraper */}
            </p>

            {(node.screenshot_url) && (
              <div className="rounded-xl overflow-hidden border border-white/10 mt-2">
                <img src={node.screenshot_url} alt="Embed" className="w-full object-cover" />
              </div>
            )}

            <div className="flex gap-6 mt-4 text-neutral-400">
              <div className="flex items-center gap-2 hover:text-blue-400 transition-colors cursor-pointer">
                <MessageCircle size={18} />
                <span>Reply</span>
              </div>
            </div>
          </div>
        </div>
        {/* Glow */}
        <div className="absolute -inset-1 bg-gradient-to-r from-[#0085ff] to-cyan-500 rounded-2xl blur-xl opacity-10 -z-10 group-hover:opacity-30 transition-opacity duration-500" />
      </div>
    );
  }

  // --- Default (Article) Card ---
  return (
    <div className="relative group w-[900px] max-w-[90vw] bg-neutral-900 rounded-2xl overflow-hidden shadow-2xl border border-white/10 hover:border-white/20 transition-all duration-500">
      {/* Image Container with 16:9 Aspect Ratio */}
      <div className="relative aspect-video w-full overflow-hidden">
        <img
          src={node.screenshot_url}
          alt={node.title}
          className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-105"
        />

        {/* Gradient Overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent opacity-80" />

        {/* Content Overlay */}
        <div className="absolute bottom-0 left-0 right-0 p-8 flex flex-col gap-4">
          <div className="flex items-center gap-2 mb-1">
            {node.feed_name && (
              <span className="bg-white/10 text-neutral-200 px-2 py-1 rounded text-xs font-bold uppercase tracking-wider">{node.feed_name}</span>
            )}
          </div>

          <h1 className="text-4xl font-bold text-white tracking-tight leading-tight shadow-md">
            {node.title}
          </h1>

          <p className="text-neutral-300 text-lg line-clamp-2 max-w-xl">
            {node.description}
          </p>

          <a
            href={node.url}
            target="_blank"
            rel="noopener noreferrer"
            className="self-start mt-2 px-8 py-3 bg-white text-black font-semibold rounded-full flex items-center gap-2 hover:bg-neutral-200 transition-colors shadow-[0_0_20px_rgba(255,255,255,0.3)] hover:shadow-[0_0_30px_rgba(255,255,255,0.5)]"
          >
            Visit Link
            <ExternalLink size={18} />
          </a>
        </div>
      </div>

      {/* Glow Effect behind the card */}
      <div className="absolute -inset-1 bg-gradient-to-r from-blue-500 to-purple-500 rounded-2xl blur-xl opacity-20 -z-10 group-hover:opacity-40 transition-opacity duration-500" />
    </div>
  );
};

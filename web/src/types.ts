export interface LinkNode {
  id: string;
  title: string;
  url: string;
  screenshot_url?: string;
  description?: string;
  feed_name?: string;
  tags?: string[];
  stats?: {
    upvotes: number;
    downvotes: number;
  };
  comments?: Comment[];
}

export interface Comment {
  user: string;
  text: string;
}

export interface SatelliteNode extends LinkNode {
  position: 'top' | 'top-left' | 'top-right' | 'left' | 'right';
  label: string;
  revealed: boolean;
  nominations: number;
  targetId: string; // To match existing usage, though backend might just send 'id'
}

export interface ActionEvent {
  type: 'react' | 'nominate' | 'rotation';
  link_id: string;
  user_id?: string;
  value?: number; // 1 or -1 for react
  ago_sec?: number;
}

export interface LinkSiteState {
  featured: {
    link: LinkNode;
    timeRemaining: number;
    totalDuration: number;
    reason: string;
  };
  satellites: SatelliteNode[];
  recentActions: ActionEvent[];
  viewerCount: number;

  // UI States managed by provider for consistency?
  // Or kept in view? 
  // Let's keep transition state in view for now as it's purely visual, 
  // but the 'rotation' event triggers it.
}

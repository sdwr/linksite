export interface Comment {
  user: string;
  text: string;
}

export interface LinkStats {
  upvotes: number;
  downvotes: number;
}

export type ConnectionPosition = 'top' | 'left' | 'right';

export interface Connection {
  targetId: string;
  label: string;
  position: ConnectionPosition;
}

export interface LinkNode {
  id: string;
  title: string;
  url: string;
  screenshot_url: string;
  description: string;
  tags: string[];
  stats: LinkStats;
  comments: Comment[];
  connections: Connection[];
}

export const MOCK_NETWORK: Record<string, LinkNode> = {
  'link-a': {
    id: 'link-a',
    title: 'The History of Sourdough',
    url: 'https://example.com/sourdough',
    screenshot_url: 'https://placehold.co/1920x1080/e2e8f0/1e293b?text=History+of+Sourdough',
    description: 'An in-depth look at how sourdough bread has been made for thousands of years.',
    tags: ['Food History', 'Baking', 'Culture'],
    stats: { upvotes: 1250, downvotes: 45 },
    comments: [
      { user: 'BakerBob', text: 'This changed how I view starter!' },
      { user: 'YeastBeast', text: 'A bit dry in the middle sections.' },
    ],
    connections: [
      { targetId: 'link-b', label: 'Scientific Basis', position: 'top' },
      { targetId: 'link-c', label: 'Location Context', position: 'left' },
      { targetId: 'link-d', label: 'Tools', position: 'right' },
    ],
  },
  'link-b': {
    id: 'link-b',
    title: 'Fermentation Science',
    url: 'https://example.com/fermentation',
    screenshot_url: 'https://placehold.co/1920x1080/dbeafe/1e3a8a?text=Fermentation+Science',
    description: 'Understanding the microbial processes behind fermentation.',
    tags: ['Science', 'Chemistry', 'Biology'],
    stats: { upvotes: 890, downvotes: 12 },
    comments: [
      { user: 'ScienceGuy', text: 'Fascinating details on lactobacillus.' },
    ],
    connections: [
      { targetId: 'link-a', label: 'Application', position: 'left' },
    ],
  },
  'link-c': {
    id: 'link-c',
    title: 'San Francisco Travel',
    url: 'https://example.com/sf-travel',
    screenshot_url: 'https://placehold.co/1920x1080/ffedd5/9a3412?text=SF+Travel',
    description: 'A guide to the best spots in San Francisco.',
    tags: ['Travel', 'USA', 'City Guide'],
    stats: { upvotes: 3400, downvotes: 120 },
    comments: [
      { user: 'Traveler99', text: 'Love the Golden Gate section.' },
    ],
    connections: [
      { targetId: 'link-a', label: 'Famous Food', position: 'right' },
    ],
  },
  'link-d': {
    id: 'link-d',
    title: 'Best Bread Knives',
    url: 'https://example.com/knives',
    screenshot_url: 'https://placehold.co/1920x1080/f1f5f9/475569?text=Bread+Knives',
    description: 'Top rated knives for cutting crusty bread.',
    tags: ['Reviews', 'Kitchen Tools', 'Shopping'],
    stats: { upvotes: 450, downvotes: 5 },
    comments: [
      { user: 'ChefCurry', text: 'The serration on #3 is perfect.' },
    ],
    connections: [
      { targetId: 'link-a', label: 'Usage', position: 'left' },
    ],
  },
};

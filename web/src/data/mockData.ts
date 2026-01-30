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
  feed_name?: string;
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
      { targetId: 'link-e', label: 'Recipes', position: 'right' },
      { targetId: 'link-f', label: 'Community', position: 'left' },
    ],
  },
  'link-b': {
    id: 'link-b',
    title: 'Sourdough Starter Science',
    url: 'https://www.youtube.com/watch?v=2FVfJtgpXnU',
    screenshot_url: 'https://img.youtube.com/vi/2FVfJtgpXnU/maxresdefault.jpg',
    description: 'A deep dive into the microbiology of your starter.',
    tags: ['Science', 'Video', 'Education'],
    stats: { upvotes: 890, downvotes: 12 },
    comments: [
      { user: 'ScienceGuy', text: 'This visual explanation is perfect.' },
    ],
    connections: [
      { targetId: 'link-a', label: 'Back to History', position: 'left' },
    ],
    feed_name: 'BreadTube',
  },
  'link-c': {
    id: 'link-c',
    title: 'My first loaf! thoughts?',
    url: 'https://www.reddit.com/r/Sourdough/comments/123456/my_first_loaf',
    screenshot_url: 'https://preview.redd.it/fake-image.jpg?auto=webp&s=123',
    description: 'u/Baker123',
    tags: ['Community', 'Feedback'],
    stats: { upvotes: 3400, downvotes: 120 },
    comments: [], // Using downvotes as comment count in mock for now
    connections: [
      { targetId: 'link-a', label: 'Inspiration', position: 'right' },
    ],
    feed_name: 'r/Sourdough',
  },
  'link-d': {
    id: 'link-d',
    title: 'Just had the best tartine in SF 🍞✨',
    url: 'https://bsky.app/profile/sourdough.fan/post/123456',
    screenshot_url: '', // Optional for Bsky
    description: 'The crust on this thing is unbelievable. #sourdough #sf',
    tags: ['Social', 'Microblog'],
    stats: { upvotes: 450, downvotes: 5 },
    comments: [
      { user: 'follower', text: 'Looks amazing!' },
    ],
    connections: [
      { targetId: 'link-a', label: 'Context', position: 'left' },
    ],
    feed_name: 'Sourdough Fan',
  },
  'link-e': {
    id: 'link-e',
    title: 'Sourdough Recipes Collection',
    url: 'https://example.com/recipes',
    screenshot_url: 'https://placehold.co/1920x1080/fff7ed/9a3412?text=Recipes',
    description: 'Classic and modern variations of sourdough loaves.',
    tags: ['Cooking', 'Recipes', 'Food'],
    stats: { upvotes: 2100, downvotes: 30 },
    comments: [
      { user: 'Yummy', text: 'The jalapeño cheddar is a must-try.' },
    ],
    connections: [
      { targetId: 'link-a', label: 'Base Technique', position: 'left' },
    ],
    feed_name: 'FoodBlog',
  },
  'link-f': {
    id: 'link-f',
    title: 'Baking Community',
    url: 'https://example.com/community',
    screenshot_url: 'https://placehold.co/1920x1080/f0abfc/4a044e?text=Community',
    description: 'Forums and groups for baking enthusiasts.',
    tags: ['Social', 'Forums'],
    stats: { upvotes: 750, downvotes: 120 },
    comments: [
      { user: 'NewUser', text: 'Very helpful people here.' },
    ],
    connections: [
      { targetId: 'link-a', label: 'Topic', position: 'right' },
    ],
  },
};

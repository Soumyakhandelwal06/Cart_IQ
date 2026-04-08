/**
 * Redis client singleton with Memory Fallback.
 * If Redis is unavailable, it uses a simple in-memory Map for development.
 */
const Redis = require('ioredis');

// Simple Memory Store fallback for development
const memoryStore = new Map();

const redisClient = new Redis(process.env.REDIS_URL || 'redis://localhost:6379', {
  retryStrategy: (times) => times > 2 ? null : 100, // Fail fast in dev
  lazyConnect: true,
  enableOfflineQueue: false,
  commandTimeout: 500,
});

let useMemory = false;

redisClient.on('connect', () => {
  console.log('✅ Redis connected');
  useMemory = false;
});

redisClient.on('error', (err) => {
  if (!useMemory) {
    console.warn('⚠️  Redis unavailable, switching to Memory Fallback:', err.message);
    useMemory = true;
  }
});

/**
 * Smart Proxy to handle GET/SET/DEL with memory fallback
 */
const redisProxy = {
  get: async (key) => {
    if (useMemory) return memoryStore.get(key);
    try {
      return await redisClient.get(key);
    } catch (err) {
      useMemory = true;
      return memoryStore.get(key);
    }
  },
  set: async (key, value, mode, duration) => {
    if (useMemory) {
      memoryStore.set(key, value);
      if (mode === 'EX') setTimeout(() => memoryStore.delete(key), duration * 1000);
      return 'OK';
    }
    try {
      return await redisClient.set(key, value, mode, duration);
    } catch (err) {
      useMemory = true;
      memoryStore.set(key, value);
      return 'OK';
    }
  },
  del: async (key) => {
    if (useMemory) return memoryStore.delete(key);
    try {
      return await redisClient.del(key);
    } catch (err) {
      useMemory = true;
      return memoryStore.delete(key);
    }
  },
  status: redisClient.status
};

module.exports = redisProxy;

const mongoose = require('mongoose');
const jwt = require('jsonwebtoken');

const userSchema = new mongoose.Schema({
  phone: {
    type: String,
    unique: true,
    required: true,
    trim: true,
  },
  name: {
    type: String,
    trim: true,
  },
  isVerified: {
    type: Boolean,
    default: false,
  },
  platformAccounts: {
    zepto: { 
      phone: String, 
      isConnected: { type: Boolean, default: false },
      storageState: Object, // Playwright context.storage_state() JSON
      lastLogin: Date 
    },
    blinkit: { 
      phone: String, 
      isConnected: { type: Boolean, default: false },
      storageState: Object,
      lastLogin: Date 
    },
    bigbasket: { 
      phone: String, 
      isConnected: { type: Boolean, default: false },
      storageState: Object,
      lastLogin: Date 
    },
  },
}, {
  timestamps: true,
});

// Standardize data for Frontend consumption
userSchema.set('toJSON', {
  transform: (doc, ret) => {
    ret.id = ret._id.toString();
    delete ret._id;
    delete ret.__v;
    return ret;
  }
});

// Generate auth token
userSchema.methods.generateAuthToken = async function () {
  const user = this;
  const token = jwt.sign(
    { id: user._id.toString(), phone: user.phone },
    process.env.JWT_SECRET || 'fallback_secret',
    { expiresIn: process.env.JWT_EXPIRES_IN || '7d' }
  );
  return token;
};

const User = mongoose.model('User', userSchema);
module.exports = User;

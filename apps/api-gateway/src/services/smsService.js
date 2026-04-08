const twilio = require('twilio');

const accountSid = process.env.TWILIO_ACCOUNT_SID;
const authToken = process.env.TWILIO_AUTH_TOKEN;
const twilioPhone = process.env.TWILIO_PHONE_NUMBER;

let client;
if (accountSid && authToken) {
  client = twilio(accountSid, authToken);
}

/**
 * Sends a 6-digit OTP to a phone number.
 * Automatically adds +91 prefix for 10-digit Indian numbers.
 */
const sendOTP = async (phone, otp) => {
  try {
    if (!client) {
      console.warn('⚠️ Twilio client not initialized. Check your credentials.');
      return false;
    }

    // Format phone number (Assume +91 if 10 digits)
    let formattedPhone = phone.trim();
    if (formattedPhone.length === 10 && !formattedPhone.startsWith('+')) {
      formattedPhone = `+91${formattedPhone}`;
    }

    const message = await client.messages.create({
      body: `Your CartIQ verification code is: ${otp}. It expires in 2 minutes.`,
      from: twilioPhone,
      to: formattedPhone,
    });

    console.log(`✅ SMS sent successfully to ${formattedPhone}. SID: ${message.sid}`);
    return true;
  } catch (err) {
    console.error('❌ Twilio Error:', err.message);
    return false;
  }
};

module.exports = { sendOTP };

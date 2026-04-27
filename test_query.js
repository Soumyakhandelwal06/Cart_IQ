const axios = require('axios');
const http = require('http');

async function run() {
  try {
    const res = await axios.post('http://localhost:3001/api/v1/query', {
      query: "tomato 1kg"
    }, {
      headers: {
        // Need to bypass auth or auth is disabled? No, auth is required.
      }
    });
    console.log(res.data);
  } catch (e) {
    console.log(e.response?.data || e.message);
  }
}
run();

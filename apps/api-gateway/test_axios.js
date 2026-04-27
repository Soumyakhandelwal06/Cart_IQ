const axios = require('axios');
axios.post('http://127.0.0.1:8001/parse/', {query: "tomato"})
  .then(res => console.log("SUCCESS:", res.status))
  .catch(err => console.log("ERROR:", err.message, err.code));

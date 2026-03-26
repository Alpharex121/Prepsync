import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: 50,
  duration: "2m",
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";

export default function () {
  const response = http.get(`${BASE_URL}/health`);
  check(response, {
    "health status is 200": (r) => r.status === 200,
  });

  sleep(0.2);
}

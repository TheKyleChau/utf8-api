"use strict";

window.addEventListener("load", () => {
  window.ui = SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true,
    displayOperationId: true,
    displayRequestDuration: true,
    docExpansion: "list",
    filter: true,
    persistAuthorization: false,
    queryConfigEnabled: false,
    requestSnippetsEnabled: true,
    supportedSubmitMethods: ["get", "post"],
    tryItOutEnabled: true,
    validatorUrl: null,
    withCredentials: false,
    presets: [SwaggerUIBundle.presets.apis],
  });
});

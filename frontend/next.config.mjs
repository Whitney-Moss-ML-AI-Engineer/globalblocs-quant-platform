/** Static export so the same build ships inside the desktop app and on S3/CloudFront. */
export default { output: "export", images: { unoptimized: true }, trailingSlash: true };

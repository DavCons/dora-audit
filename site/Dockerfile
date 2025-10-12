FROM nginx:stable
RUN rm -rf /usr/share/nginx/html/*
COPY . /usr/share/nginx/html/
COPY nginx/conf.d/10-site.conf /etc/nginx/conf.d/10-site.conf
COPY nginx/conf.d/blank.conf /etc/nginx/conf.d/default.conf
# disable default server without needing blank.conf
#RUN rm -f /etc/nginx/conf.d/default.conf

#FROM nginx:alpine
#COPY . /usr/share/nginx/html/
#COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80

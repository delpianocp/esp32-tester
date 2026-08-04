from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from devices import views as device_views
from devices.account_forms import LoginForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('devices.urls')),
    path('api/', include('api.urls')),
    path(
        'accounts/login/',
        auth_views.LoginView.as_view(template_name='registration/login.html', authentication_form=LoginForm),
        name='login',
    ),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='devices:list'), name='logout'),
    path('accounts/registro/', device_views.registro, name='registro'),
]



# from django.shortcuts import render
# from django.views import View
# from django.contrib.auth import authenticate, login


# from .forms import RegisterUserForm

# from django.shortcuts import redirect

# # Create your views here.

# class RegisterUser(View):
#     template_name = "users/register.html"

#     def get(self, request):
#         context = {
#             "form": RegisterUserForm(),
#             "title": "регистрация",
#         }
#         return render(request, self.template_name, context)

#     def post(self, request):
#         form = RegisterUserForm(request.POST, request.FILES)
#         if form.is_valid():
#             user = form.save()
#             email = form.cleaned_data.get("email")
#             password = form.cleaned_data.get("password1")
#             user = authenticate(request, username=email, password=password)
#             login(request, user, backend="users.authentication.EmailAuthBackend")
#             return redirect("users:profile")
#         context = {
#             "form": form,
#         }
#         return render(request, self.template_name, context)
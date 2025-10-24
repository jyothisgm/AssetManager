from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django.contrib import admin

User = get_user_model()
UserAdmin = admin.site._registry[User].__class__  # Get the existing admin class

@staff_member_required
def my_profile_view(request):
    """
    Admin self-update page using the default UserAdmin form,
    but restricted to the logged-in user and limited fields.
    """
    user = request.user
    model_admin = UserAdmin(User, admin.site)
    form_class = model_admin.get_form(request, obj=user)

    # Limit editable fields
    limited_fields = ['first_name', 'last_name', 'email']
    form = form_class(request.POST or None, instance=user)

    # Dynamically limit fields
    for field_name in list(form.fields.keys()):
        if field_name not in limited_fields:
            form.fields.pop(field_name)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, "✅ Your profile has been updated successfully.")
        return redirect('admin:my_profile')

    context = {
        **admin.site.each_context(request),
        'opts': User._meta,
        'title': 'My Profile',
        'form': form,
        'is_popup': False,
    }
    return render(request, 'admin/my_profile.html', context)

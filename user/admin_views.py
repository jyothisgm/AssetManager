from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django.contrib import admin
from common.logging_config import logger

User = get_user_model()
UserAdmin = admin.site._registry[User].__class__  # Get the existing admin class


@staff_member_required
def my_profile_view(request):
    """
    Admin self-update page using the default UserAdmin form,
    but restricted to the logged-in user and limited fields.
    """
    func_name = "my_profile_view"
    user = request.user

    try:
        logger.debug(f"[{func_name}] Accessed by staff user: {user.email}")

        model_admin = UserAdmin(User, admin.site)
        form_class = model_admin.get_form(request, obj=user)

        # Limit editable fields
        limited_fields = ['first_name', 'last_name', 'email']
        form = form_class(request.POST or None, instance=user)

        # Dynamically limit fields
        for field_name in list(form.fields.keys()):
            if field_name not in limited_fields:
                form.fields.pop(field_name)
        logger.debug(f"[{func_name}] Limited editable fields to: {limited_fields}")

        if request.method == 'POST':
            logger.debug(f"[{func_name}] POST request received from {user.email}")
            if form.is_valid():
                form.save()
                messages.success(request, "✅ Your profile has been updated successfully.")
                logger.info(f"[{func_name}] Profile updated successfully for user={user.email}")
                return redirect('admin:my_profile')
            else:
                logger.warning(f"[{func_name}] Invalid form submission by {user.email} | Errors: {form.errors}")

        context = {
            **admin.site.each_context(request),
            'opts': User._meta,
            'title': 'My Profile',
            'form': form,
            'is_popup': False,
        }
        logger.debug(f"[{func_name}] Rendering profile page for {user.email}")
        return render(request, 'admin/my_profile.html', context)

    except Exception as e:
        logger.exception(f"[{func_name}] Error processing profile update for user={getattr(user, 'email', None)}")
        raise e

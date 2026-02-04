<script lang="ts">
	import { getContext } from 'svelte';
	import { LinkPreview } from 'bits-ui';

	const i18n = getContext('i18n');
	import { getUserById } from '$lib/apis/users';

	import UserStatus from './UserStatus.svelte';

	export let id = null;
	export let userData = null; // Optional: pre-fetched user data

	export let side = 'top';
	export let align = 'start';
	export let sideOffset = 6;

	let user = userData; // Use pre-fetched data if available
	let loading = false;

	// Lazy load user data only when needed (on hover)
	async function loadUserOnDemand() {
		// Only fetch if we don't already have user data
		if (id && !user && !loading) {
			loading = true;
			user = await getUserById(localStorage.token, id).catch((error) => {
				console.error('Error fetching user by ID:', error);
				return null;
			});
			loading = false;
		}
	}

	// Watch for userData changes (when passed from parent)
	$: if (userData) {
		user = userData;
	}
</script>

{#if user}
	<LinkPreview.Content
		class="w-full max-w-[260px] rounded-2xl border border-gray-100  dark:border-gray-800 z-[9999] bg-white dark:bg-gray-850 dark:text-white shadow-lg transition"
		{side}
		{align}
		{sideOffset}
		on:mouseenter={loadUserOnDemand}
	>
		<UserStatus {user} />
	</LinkPreview.Content>
{:else if loading}
	<LinkPreview.Content
		class="w-full max-w-[260px] rounded-2xl border border-gray-100  dark:border-gray-800 z-[9999] bg-white dark:bg-gray-850 dark:text-white shadow-lg transition"
		{side}
		{align}
		{sideOffset}
	>
		<div class="p-4 text-sm text-gray-500 dark:text-gray-400">{$i18n.t('Loading...')}</div>
	</LinkPreview.Content>
{/if}
